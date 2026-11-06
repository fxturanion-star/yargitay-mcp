"""Bedesten adaylarının Türkçe pasajlarını çok dilli E5 vektörleriyle sırala."""
import asyncio
import hashlib
import os
import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import httpx
import bedesten

MODEL = "Xenova/multilingual-e5-small"
REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
FILES = {"tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
         "onnx/model_quantized.onnx": "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193"}
_inference = threading.Lock()
_workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix="semantic-model")
_slots = asyncio.BoundedSemaphore(3)


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
            with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(65536):
                    if file.tell() + len(chunk) > 128 * 1024 * 1024:
                        raise ValueError("Model dosyası boyut sınırını aştı.")
                    file.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest() != FILES[name]:
            raise ValueError("Semantik model dosyasının özeti doğrulanamadı.")
        os.replace(temp, path)
        return path
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
    future.add_done_callback(lambda _: _slots.release())
    return await asyncio.shield(future)


_HOME = re.compile(r"\b(?:konut\w*|mesken\w*|ikametg[aâ]h\w*|ev(?:i|in|de|den|ler|e)\w*|kaldığı yer)", re.I)
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


def _passages(text):
    size, stride, limit = 680, 500, 20
    last = max(0, len(text) - size)
    count = min(limit, 1 + (last + stride - 1) // stride)
    for i in range(count):
        start = last * i // max(1, count-1)
        yield start, text[start:start+size]


def register(mcp, search, read):
    @mcp.tool(annotations={"readOnlyHint": True})
    async def semantik_ictihat_ara(soru: str, arama_ifadeleri: list[str] | None = None,
                                  daire: str = "", baslangic_tarihi: str = "", bitis_tarihi: str = "",
                                  aday_sayisi: int = 3, sonuc_sayisi: int = 3) -> dict:
        """Hukuki soruya en yakın Yargıtay pasajlarını Bedesten adayları içinde sırala.
        İstemci soru için 1–3 kısa alternatif arama ifadesi verebilir. Tarihler GG.AA.YYYY.
        Benzerlik, hukuki destek veya çoğunluk görüşü doğrulaması sağlamaz."""
        question = soru.strip()
        if not 4 <= len(question) <= 1200 or not 1 <= aday_sayisi <= 6 or not 1 <= sonuc_sayisi <= 6:
            raise ValueError("Soru 4–1200 karakter, aday ve sonuç sayıları 1–6 olmalı.")
        phrases = _phrases(question, arama_ifadeleri)
        groups = []
        errors = []
        for phrase in phrases:
            # Hatalı filtre veya kaynak kesintisi boş sonuç olarak sunulmaz.
            result = await search(aranan_kelime=phrase, daire=daire, baslangic_tarihi=baslangic_tarihi,
                                  bitis_tarihi=bitis_tarihi, sayfa_boyutu=aday_sayisi)
            groups.append(result["kararlar"])
        candidates = {}
        for i in range(aday_sayisi):
            for group in groups:
                if i < len(group):
                    candidates.setdefault(group[i]["id"], group[i])
        passages = []
        inspected = []
        home_search = _home_search(question)
        rejected = 0
        for card in list(candidates.values())[:aday_sayisi]:
            try:
                text = await read(card["id"])
                if not text.strip():
                    raise ValueError("Boş karar metni.")
                verified, status = await bedesten.resolve_card(card["id"], " ".join(text[:500].split()))
                if not verified:
                    errors.append({"id":card["id"], "neden":status})
                    continue
            except (httpx.HTTPError, ValueError, RuntimeError, LookupError) as exc:
                errors.append({"id":card["id"], "neden":str(exc)[:250]})
                continue
            inspected.append(card["id"])
            for start, excerpt in _passages(text):
                if home_search and not _home_search(excerpt):
                    rejected += 1
                    continue
                passages.append({**verified, "kunye_durumu":status, "pasaj":excerpt, "baslangic":start,
                                 "bitis":start+len(excerpt)})
        if candidates and not inspected:
            raise RuntimeError(f"Aday kararların metni veya künyesi doğrulanamadı: {errors}")
        top = {}
        if passages:
            scores = await _score(question, [p["pasaj"] for p in passages])
            for passage, score in zip(passages, scores, strict=True):
                doc = passage["id"]
                if doc not in top or score > top[doc]["benzerlik"]:
                    top[doc] = {**passage, "benzerlik":score}
        ranked = sorted(top.values(), key=lambda p:p["benzerlik"], reverse=True)
        return {"durum":"deneysel", "pasaj_odagi":"konutta arama" if home_search else None,
                "odak_disi_pasaj":rejected, "kapsam":"Bedesten aramalarından seçilen aday kararların örneklenen pasajları",
                "arama_ifadeleri":phrases, "incelenen_aday":len(inspected), "incelenen_pasaj":len(passages),
                "model":MODEL, "hukuki_uygunluk_dogrulandi":False, "pasaj_sahibi_dogrulandi":False,
                "sonuclar":ranked[:sonuc_sayisi], "hatalar":errors}
