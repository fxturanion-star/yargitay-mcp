"""Adalet Bakanlığı Mevzuat ve İçtihat Programının resmî arama ve belge servisi."""
import asyncio
import base64
import binascii
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from cachetools import TTLCache
import upstream

BASE = "https://bedesten.adalet.gov.tr"
SITE = "https://mevzuat.adalet.gov.tr"
_kunyeler = TTLCache(maxsize=1000, ttl=900)
_searches = TTLCache(maxsize=64, ttl=60)
_search_locks = [asyncio.Lock() for _ in range(16)]


async def request(path, data, paging=False):
    body = {"data": data}
    if paging:
        body["paging"] = True
    async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=6)) as client:
        response = await upstream.request(client, "POST", BASE + path, json=body)
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("metadata", {}), dict):
        raise ValueError("Bedesten yanıt şeması değişti.")
    if payload.get("metadata", {}).get("FMTY") == "ERROR":
        raise RuntimeError(str(payload["metadata"].get("FMTE", "Bedesten sorgu hatası")))
    if not isinstance(payload.get("data"), dict):
        raise RuntimeError("Bedesten yanıt yapısı doğrulanamadı.")
    return payload["data"]


def rows(data, key):
    if not isinstance(data.get(key), list) or not isinstance(data.get("total"), int):
        raise RuntimeError("Resmî servis sonuç sayısını ve listesini doğrulayamadı.")
    return data[key]


async def search_page(path, params, key):
    """Kaynak en çok 20 kayıt verir; istemcinin sayfa sınırlarını koru."""
    size, number = params["pageSize"], params["pageNumber"]
    if size <= 20:
        return await request(path, params, True)
    start = (number - 1) * size
    page, skip = divmod(start, 20)
    found = []
    while len(found) < size:
        page += 1
        data = await request(path, {**params, "pageSize": 20, "pageNumber": page}, True)
        batch = rows(data, key)
        found.extend(batch[skip:])
        skip = 0
        if page * 20 >= data["total"] or not batch:
            break
    return {key: found[:size], "total": data["total"]}


async def judgments(query):
    cache_key = tuple(sorted(query.items()))
    if any(isinstance(value, str) and len(value) > 2000 for value in query.values()):
        raise ValueError("Arama alanı 2000 karakteri aşamaz.")
    async with _search_locks[hash(cache_key) % len(_search_locks)]:
        if cache_key not in _searches:
            _searches[cache_key] = await _search_judgments(query)
        return _searches[cache_key]


async def _search_judgments(query):
    params = {"itemTypeList": ["YARGITAYKARARI"],
              "pageSize": query["pageSize"], "pageNumber": query["pageNumber"]}
    if query["aranan"].strip():
        params["phrase"] = query["aranan"]
    for old, new in (("birimYrgKurulDaire", "birimAdi"), ("esasYil", "esasNoYil"),
                     ("kararYil", "kararNoYil")):
        if old in query:
            params[new] = query[old]
    for stem, new in (("esas", "esasNoSira"), ("karar", "kararNoSira")):
        lo, hi = query.get(stem+"IlkSiraNo"), query.get(stem+"SonSiraNo")
        if lo or hi:
            if lo != hi:
                raise ValueError("Bedesten sıra numarası aralığı desteklemiyor. Kesin numara için iki sınırı eşit girin.")
            params[new] = lo
    for old, new in (("baslangicTarihi", "kararTarihiStart"), ("bitisTarihi", "kararTarihiEnd")):
        if old in query:
            dt = datetime.strptime(query[old], "%d.%m.%Y")
            params[new] = dt.strftime("%Y-%m-%d") + ("T00:00:00" if old=="baslangicTarihi" else "T23:59:59.999")
    data = await search_page("/emsal-karar/searchDocuments", params, "emsalKararList")
    results = []
    for row in rows(data, "emsalKararList"):
        fields = ("documentId", "birimAdi", "esasNo", "kararNo", "kararTarihiStr")
        if not isinstance(row, dict) or any(row.get(k) is None for k in fields):
            raise ValueError("Bedesten karar künyesi eksik.")
        doc = str(row["documentId"])
        results.append({"id": "bedesten:"+doc, "daire": row["birimAdi"], "esas_no": row["esasNo"],
                        "karar_no": row["kararNo"], "karar_tarihi": row["kararTarihiStr"],
                        "kaynak": f"{SITE}/ictihat/{doc}"})
    for card in results:
        _kunyeler[card["id"]] = card
    result = {"toplam_sonuc": data["total"], "sayfa": params["pageNumber"], "sayfa_boyutu": params["pageSize"],
            "kararlar": results, "kaynak": "Adalet Bakanlığı Bedesten / Yargıtay"}
    return result


async def document(doc, law=False, article=False):
    if not doc.isascii() or not doc.isdigit() or len(doc)>20:
        raise ValueError("Belge kimliği geçersiz.")
    path, params = (("/mevzuat/getDocumentContent", {"documentType":"MADDE" if article else "MEVZUAT","id":doc})
                    if law or article else ("/emsal-karar/getDocumentContent", {"documentId":doc}))
    data = await request(path, params)
    encoded = data.get("content")
    if not isinstance(encoded, str) or not encoded.strip():
        raise LookupError("Bedesten belge içeriği döndürmedi.")
    try:
        raw = base64.b64decode("".join(encoded.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Bedesten belge kodlaması doğrulanamadı.") from exc
    mime = str(data.get("mimeType") or data.get("mimetype") or "").lower()
    if raw.startswith(b"%PDF"):
        import io
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
    elif "html" in mime or raw.lstrip().startswith(b"<"):
        soup = BeautifulSoup(raw, "html.parser", from_encoding="utf-8")
        for tag in soup(["style","script"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
    else:
        raise ValueError("Belge biçimi desteklenmiyor: "+mime)
    if not text.strip():
        raise ValueError("Kaynak okunabilir metin döndürmedi.")
    return text


async def mevzuat_genel_ara(ifade: str, tur: str = "", sayfa: int = 1, adet: int = 10) -> dict:
    """Tüm indekslenen mevzuat türlerini ara. Tür boşsa tümü; örnek KANUN, KKY, UY, TEBLIGLER, KHK, MULGA. Statü belge bazında kontrol edilmelidir."""
    if sayfa < 1 or not 1 <= adet <= 50:
        raise ValueError("Sayfa en az 1, adet 1–50 olmalı.")
    params = {"pageSize": adet, "pageNumber": sayfa}
    if ifade.strip():
        params["phrase"] = ifade.strip()
    if tur:
        params["mevzuatTurList"] = [tur.upper()]
    data = await search_page("/mevzuat/searchDocuments", params, "mevzuatList")
    results = [{"id": str(r["mevzuatId"]), "ad": r["mevzuatAdi"], "no": r.get("mevzuatNo"),
                "tur": r.get("mevzuatTur"), "resmi_gazete_tarihi":r.get("resmiGazeteTarihi"),
                "kaynak": f"{SITE}/mevzuat/{r['mevzuatId']}"} for r in rows(data, "mevzuatList")]
    return {"sonuclar":results, "toplam":data["total"], "sayfa":sayfa}


async def mevzuat_belgesi_getir(belge_id: str, baslangic: int = 0) -> dict:
    """Genel mevzuat aramasındaki belgeyi resmî kaynaktan getir. Uzun belgelerde sonraki_baslangic ile devam et."""
    if baslangic < 0:
        raise ValueError("Başlangıç negatif olamaz.")
    text = await document(belge_id, law=True)
    if baslangic >= len(text):
        raise ValueError("Başlangıç belge uzunluğunu aşıyor.")
    end = baslangic + 20000
    return {"metin":text[baslangic:end], "toplam_karakter":len(text),
            "sonraki_baslangic":end if end < len(text) else None, "kaynak":f"{SITE}/mevzuat/{belge_id}",
            "erisim_zamani":datetime.now(timezone.utc).isoformat()}
