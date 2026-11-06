"""Bedesten adaylarının Türkçe pasajlarını çok dilli E5 vektörleriyle sırala."""
import asyncio
import hashlib
import os
import re
import tempfile
import threading
import time
import math
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import httpx
import bedesten
from passage_selection import select_passages

MODEL = "Xenova/multilingual-e5-small"
REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
FILES = {"tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
         "onnx/model_quantized.onnx": "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193"}
_inference = threading.Lock()
_workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix="semantic-model")
_slots = asyncio.BoundedSemaphore(3)
_requests = asyncio.BoundedSemaphore(2)


def _asset(name):
    folder = Path(os.getenv("SEMANTIK_MODEL_CACHE", Path.home() / ".cache" / "yargitay-mcp")) / REVISION
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / Path(name).name
    if path.is_file():
        with path.open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() == FILES[name]:
                return path
    url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}"
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, delete=False) as file:
            temp = Path(file.name)
            digest = hashlib.sha256()
            deadline = time.monotonic() + 180
            with httpx.stream("GET", url, follow_redirects=True, timeout=30) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(65536):
                    if time.monotonic() > deadline:
                        raise RuntimeError("Semantik model indirme süresi doldu.")
                    if file.tell() + len(chunk) > 128 * 1024 * 1024:
                        raise ValueError("Model dosyası boyut sınırını aştı.")
                    file.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest() != FILES[name]:
            raise ValueError("Semantik model dosyasının özeti doğrulanamadı.")
        os.replace(temp, path)
        return path
    except httpx.HTTPError as exc:
        raise RuntimeError("Semantik model indirilemedi: " + type(exc).__name__) from None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


@lru_cache(maxsize=1)
def _model():
    import onnxruntime as ort
    from tokenizers import Tokenizer

    ort.disable_telemetry_events()
    tokenizer = Tokenizer.from_file(str(_asset("tokenizer.json")))
    tokenizer.enable_truncation(max_length=256)
    tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(_asset("onnx/model_quantized.onnx")), options,
                                   providers=["CPUExecutionProvider"])
    return tokenizer, session


def similarities(question, passages):
    """Bir sorgu için E5 kosinüs benzerlikleri, pasajların girdi sırasıyla."""
    import numpy as np

    with _inference:
        tokenizer, session = _model()
        tokenizer.no_truncation()
        query_size = len(tokenizer.encode("query: " + question).ids)
        tokenizer.enable_truncation(max_length=256)
        if query_size > 256:
            raise ValueError("Soru modelin 256 token sınırını aşıyor; soruyu kısaltın.")
        texts = ["query: " + question] + ["passage: " + text for text in passages]
        vectors = []
        for start in range(0, len(texts), 8):
            encoded = tokenizer.encode_batch(texts[start:start+8])
            mask = np.asarray([entry.attention_mask for entry in encoded], dtype=np.int64)
            tokens = np.asarray([entry.ids for entry in encoded], dtype=np.int64)
            hidden = session.run(["last_hidden_state"], {"input_ids": tokens, "attention_mask":mask,
                                                         "token_type_ids":np.zeros_like(tokens)})[0]
            pooled = (hidden * mask[:, :, None]).sum(axis=1) / mask.sum(axis=1)[:, None]
            vectors.extend(pooled / np.linalg.norm(pooled, axis=1, keepdims=True))
        return [float(v @ vectors[0]) for v in vectors[1:]]


async def _score(question, passages):
    if _slots.locked():
        raise RuntimeError("Semantik model meşgul; daha sonra tekrar deneyin.")
    await _slots.acquire()
    loop = asyncio.get_running_loop()
    try:
        future = loop.run_in_executor(_workers, similarities, question, passages)
    except BaseException:
        _slots.release()
        raise
    # İstemci bağlantıyı kesse dahi çalışan iş bitene kadar yerini korur.
    def finished(done):
        _slots.release()
        if not done.cancelled():
            done.exception()  # İptal edilen istemciden sonra kalan işin hatasını tüket.
    future.add_done_callback(finished)
    return await asyncio.shield(future)


_HOME = re.compile(r"\b(?:konut\w*|mesken\w*|ikametg[aâ]h\w*|ev(?:i|in|inde|inden|ine|ini|de|den|e|indeki|ler(?:i|inde|inden)?)?\b|kaldığı yer)", re.I)
_SEARCH = re.compile(r"\bara(?:ma|n|t)\w*", re.I)


def _home_search(text):
    return bool(_HOME.search(text) and _SEARCH.search(text))


def _phrases(question, supplied):
    if supplied is not None:
        if not 1 <= len(supplied) <= 3 or any(not s.strip() or len(s) > 120 for s in supplied):
            raise ValueError("Bir ila üç kısa Bedesten arama ifadesi verin.")
        return list(dict.fromkeys(s.strip() for s in supplied))
    lowered = question.lower().replace("i\u0307", "i")
    if _home_search(lowered):
        return ['"konutta arama"', '"konut araması"', '"arama kararı"']
    if "arama" in lowered and any(w in lowered for w in ("kolluk", "konut", "şüphe", "istihbarat", "emare")):
        return ['"makul şüphe"', '"arama kararı"', '"istihbari bilgi"']
    if "tutuk" in lowered and "şüphe" in lowered:
        return ['"kuvvetli suç şüphesi"', '"tutuklama nedenleri"']
    stop = {"ilişkin", "hakkında", "kararları", "yargıtay", "hangi", "nasıl", "bulmak", "kararlarını",
            "mümkün", "olduğu", "olmadığı", "durumda", "göre", "ilgili"}
    terms = [word for word in re.findall(r"[^\W\d_]{4,}", lowered) if word not in stop]
    return list(dict.fromkeys(terms))[:3] or [question[:120]]


def _passages(text, question="", limit=20):
    return select_passages(text, question, limit)


def _limit(name, default, maximum):
    value = int(os.getenv(name, str(default)))
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} 1–{maximum} aralığında olmalı.")
    return value


def _candidate_pool(groups, limit):
    cards, scores, sources = {}, {}, {}
    for group_no, group in enumerate(groups):
        seen = set()
        for rank, card in enumerate(group, 1):
            key = card["id"]
            if key in seen:
                continue
            seen.add(key)
            cards.setdefault(key, card)
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
            sources.setdefault(key, set()).add(group_no)
    ordered = sorted(cards, key=lambda key: -scores[key])
    selected, covered = [], set()
    for key in ordered:
        if sources[key] - covered:
            selected.append(key)
            covered.update(sources[key])
        if len(selected) == limit:
            break
    selected.extend(key for key in ordered if key not in selected)
    return [cards[key] for key in selected[:limit]]


def _source_error(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Kaynak HTTP {exc.response.status_code} döndürdü."
    return "Kaynak veya künye doğrulanamadı (" + type(exc).__name__ + ")."


def register(mcp, search, read):
    @mcp.tool(annotations={"readOnlyHint": True})
    async def semantik_ictihat_ara(soru: str, arama_ifadeleri: list[str] | None = None,
                                  daire: str = "", baslangic_tarihi: str = "", bitis_tarihi: str = "",
                                  aday_sayisi: int = 3, sonuc_sayisi: int = 3) -> dict:
        """Hukuki soruya en yakın Yargıtay pasajlarını Bedesten adayları içinde sırala.
        İstemci soru için 1–3 kısa alternatif arama ifadesi verebilir. Tarihler GG.AA.YYYY.
        Benzerlik, hukuki destek veya çoğunluk görüşü doğrulaması sağlamaz."""
        if _requests.locked() or _slots.locked():
            raise RuntimeError("Semantik sorgu kapasitesi dolu; daha sonra deneyin.")
        await _requests.acquire()
        try:
            return await _run(soru, arama_ifadeleri, daire, baslangic_tarihi, bitis_tarihi,
                              aday_sayisi, sonuc_sayisi)
        finally:
            _requests.release()

    async def _run(soru, arama_ifadeleri, daire, baslangic_tarihi, bitis_tarihi, aday_sayisi, sonuc_sayisi):
        max_documents = _limit("SEMANTIK_MAX_DOCUMENTS", 6, 12)
        pool_limit = _limit("SEMANTIK_CANDIDATE_POOL", 18, 60)
        per_doc = _limit("SEMANTIK_PASSAGES_PER_DOC", 20, 36)
        passage_limit = _limit("SEMANTIK_MAX_PASSAGES", 120, 240)
        max_chars = _limit("SEMANTIK_MAX_TEXT_CHARS", 500000, 2000000)
        question = soru.strip()
        if not 4 <= len(question) <= 1200 or not 1 <= aday_sayisi <= max_documents or not 1 <= sonuc_sayisi <= 6:
            raise ValueError(f"Soru 4–1200 karakter, aday sayısı 1–{max_documents}, sonuç sayısı 1–6 olmalı.")
        phrases = _phrases(question, arama_ifadeleri)
        groups = []
        errors = []
        page_size = max(1, min(20, (pool_limit + len(phrases)-1) // len(phrases)))
        for phrase in phrases:
            # Hatalı filtre veya kaynak kesintisi boş sonuç olarak sunulmaz.
            result = await search(aranan_kelime=phrase, daire=daire, baslangic_tarihi=baslangic_tarihi,
                                  bitis_tarihi=bitis_tarihi, sayfa_boyutu=page_size)
            groups.append(result["kararlar"])
        candidates = _candidate_pool(groups, pool_limit)
        to_read = candidates[:min(aday_sayisi, passage_limit)]
        per_doc = min(per_doc, max(1, passage_limit // max(1, len(to_read))))
        passages = []
        inspected = []
        home_search = _home_search(question)
        rejected = 0
        scanned_chars = 0
        for card in to_read:
            try:
                text = await read(card["id"])
                if len(text) > max_chars:
                    raise ValueError("Karar semantik metin boyutu sınırını aşıyor.")
                if not text.strip():
                    raise ValueError("Boş karar metni.")
                verified, status = await bedesten.resolve_card(card["id"], " ".join(text[:500].split()))
                if not verified:
                    errors.append({"id":card["id"], "neden":status})
                    continue
            except (httpx.HTTPError, ValueError, RuntimeError, LookupError) as exc:
                errors.append({"id":card["id"], "neden":_source_error(exc)})
                continue
            inspected.append(card["id"])
            scanned_chars += len(text)
            for start, excerpt in _passages(text, question, per_doc):
                if home_search and not _home_search(excerpt):
                    rejected += 1
                passages.append({**verified, "kunye_durumu":status, "pasaj":excerpt, "baslangic":start,
                                 "bitis":start+len(excerpt)})
        if candidates and not inspected:
            raise RuntimeError(f"Aday kararların metni veya künyesi doğrulanamadı: {errors}")
        top = {}
        if passages:
            scores = await _score(question, [p["pasaj"] for p in passages])
            for passage, score in zip(passages, scores, strict=True):
                if not math.isfinite(score):
                    raise ValueError("Semantik model sonlu bir skor döndürmedi.")
                doc = passage["id"]
                if doc not in top or score > top[doc]["benzerlik"]:
                    top[doc] = {**passage, "benzerlik":score}
        ranked = sorted(top.values(), key=lambda p:p["benzerlik"], reverse=True)
        return {"durum":"deneysel", "pasaj_odagi":"konutta arama" if home_search else None,
                "odak_disi_pasaj":rejected, "odak_filtresi":"yalnız bilgi, eleme yapılmaz",
                "aday_havuzu":len(candidates), "kaynak_sorgu_sayisi":len(phrases),
                "metin_okuma_denemesi":len(to_read), "taranan_karakter":scanned_chars, "kapsam":"Bedesten aramalarından seçilen aday kararların örneklenen pasajları",
                "arama_ifadeleri":phrases, "incelenen_aday":len(inspected), "incelenen_pasaj":len(passages),
                "model":MODEL, "hukuki_uygunluk_dogrulandi":False, "pasaj_sahibi_dogrulandi":False,
                "sonuclar":ranked[:sonuc_sayisi], "hatalar":errors}

    return semantik_ictihat_ara
