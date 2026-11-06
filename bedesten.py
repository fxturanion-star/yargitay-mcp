"""Adalet Bakanlığı Mevzuat ve İçtihat Programının resmî arama ve belge servisi."""
import asyncio
import base64
import binascii
import math
from email.utils import parsedate_to_datetime
import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

BASE = "https://bedesten.adalet.gov.tr"
SITE = "https://mevzuat.adalet.gov.tr"
_lock = asyncio.Lock()
_last_request = 0.0
_blocked_until = 0.0


def _retry_seconds(header):
    if header and header.isascii() and header.isdigit():
        return max(1, int(header))
    if header:
        try:
            return max(1, math.ceil(parsedate_to_datetime(header).timestamp() - time.time()))
        except (ValueError, TypeError, OverflowError):
            pass
    return 60


async def request(path, data, paging=False):
    global _last_request, _blocked_until
    body = {"data": data}
    if paging:
        body["paging"] = True
    async with _lock:
        remaining = _blocked_until - time.monotonic()
        if remaining > 0:
            raise RuntimeError(f"Bedesten istek sınırı: {math.ceil(remaining)} saniye sonra deneyin.")
        await asyncio.sleep(max(0, 3 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=6)) as client:
            response = await client.post(BASE + path, json=body)
        if response.status_code == 429:
            delay = _retry_seconds(response.headers.get("Retry-After"))
            _blocked_until = time.monotonic() + delay
            raise RuntimeError(f"Bedesten istek sınırı: {delay} saniye sonra deneyin.")
        response.raise_for_status()
    payload = response.json()
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
        doc = str(row["documentId"])
        results.append({"id": "bedesten:"+doc, "daire": row["birimAdi"], "esas_no": row["esasNo"],
                        "karar_no": row["kararNo"], "karar_tarihi": row["kararTarihiStr"],
                        "kaynak": f"{SITE}/ictihat/{doc}"})
    return {"toplam_sonuc": data["total"], "sayfa": params["pageNumber"], "sayfa_boyutu": params["pageSize"],
            "kararlar": results, "kaynak": "Adalet Bakanlığı Bedesten / Yargıtay"}


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
