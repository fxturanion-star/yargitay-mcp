"""Adalet Bakanlığı Mevzuat ve İçtihat Programının resmî arama ve belge servisi."""
import asyncio
import base64
import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

BASE = "https://bedesten.adalet.gov.tr"
SITE = "https://mevzuat.adalet.gov.tr"
_lock = asyncio.Lock()
_last_request = 0.0


async def request(path, data, paging=False):
    global _last_request
    body = {"data": data}
    if paging:
        body["paging"] = True
    async with _lock:
        await asyncio.sleep(max(0, 1 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=6)) as client:
            response = await client.post(BASE + path, json=body)
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
    data = await request("/emsal-karar/searchDocuments", params, True)
    results = []
    for row in rows(data, "emsalKararList"):
        doc = str(row["documentId"])
        results.append({"id": "bedesten:"+doc, "daire": row["birimAdi"], "esas_no": row["esasNo"],
                        "karar_no": row["kararNo"], "karar_tarihi": row["kararTarihiStr"],
                        "kaynak": f"{SITE}/ictihat/{doc}"})
    return {"toplam_sonuc": data["total"], "sayfa": params["pageNumber"], "sayfa_boyutu": params["pageSize"],
            "kararlar": results, "kaynak": "Adalet Bakanlığı Bedesten / Yargıtay"}


async def document(doc, law=False):
    if not doc.isascii() or not doc.isdigit() or len(doc)>20:
        raise ValueError("Belge kimliği geçersiz.")
    path, params = (("/mevzuat/getDocumentContent", {"documentType":"MEVZUAT","id":doc})
                    if law else ("/emsal-karar/getDocumentContent", {"documentId":doc}))
    data = await request(path, params)
    raw = base64.b64decode(data["content"])
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
    params = {"phrase": ifade, "pageSize": adet, "pageNumber": sayfa}
    if tur:
        params["mevzuatTurList"] = [tur.upper()]
    data = await request("/mevzuat/searchDocuments", params, True)
    results = [{"id": str(r["mevzuatId"]), "ad": r["mevzuatAdi"], "no": r.get("mevzuatNo"),
                "tur": r.get("mevzuatTur"), "resmi_gazete_tarihi":r.get("resmiGazeteTarihi"),
                "kaynak": f"{SITE}/mevzuat/{r['mevzuatId']}"} for r in rows(data, "mevzuatList")]
    return {"sonuclar":results, "toplam":data["total"], "sayfa":sayfa}


async def mevzuat_belgesi_getir(belge_id: str, baslangic: int = 0) -> dict:
    """Genel mevzuat aramasındaki belgeyi resmî kaynaktan getir. Uzun belgelerde sonraki_baslangic ile devam et."""
    if baslangic < 0:
        raise ValueError("Başlangıç negatif olamaz.")
    text = await document(belge_id, law=True)
    end = baslangic + 20000
    return {"metin":text[baslangic:end], "toplam_karakter":len(text),
            "sonraki_baslangic":end if end < len(text) else None, "kaynak":f"{SITE}/mevzuat/{belge_id}",
            "erisim_zamani":datetime.now(timezone.utc).isoformat()}
