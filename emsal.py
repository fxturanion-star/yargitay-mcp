"""Bireysel başvuru araştırması ve kaynağa dayalı önerme denetimi."""
import re
import uuid
from typing import Literal

import bedesten
import upstream
import httpx
from bs4 import BeautifulSoup

AYM = "https://kararlarbilgibankasi.anayasa.gov.tr"
_verdict = Literal["destekliyor", "kısmen destekliyor", "başka meseleyi tartışıyor", "doğrulanamadı"]
_role = Literal["mahkemenin gerekçesi", "taraf iddiası", "tebliğname", "karşıoy", "başka karardan alıntı", "hüküm", "belirsiz"]


async def _records(params):
    async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=8)) as client:
        response = await upstream.request(client, "POST", AYM + "/api/core/public/search",
                                     json={"kararTipi":"BireyselBasvuru", **params})
        response.raise_for_status()
        payload = upstream.json_object(response, "AYM")
    if (not isinstance(payload, dict) or not isinstance(payload.get("data"), list)
            or any(not isinstance(row, dict) or not row.get("id") for row in payload["data"])):
        raise ValueError("AYM sonuç listesi doğrulanamadı.")
    return payload


def _card(row):
    no = row.get("basvuruNo") or ""
    return {"id":row["id"], "basvuru_no":no, "ad":row.get("basvuruAdi"),
            "karar_tarihi":row.get("kararTarihi"), "sonuc":row.get("kararTuruBasvuruSonucuLabel"),
            "kaynak":f"{AYM}/BB/{no}" if no else None}


async def aym_ara(ifade: str, sayfa: int = 1, adet: int = 10) -> dict:
    """AYM bireysel başvuru kararlarını arar. Kesin ifadeyi çift tırnak içine alın."""
    if not ifade.strip() or sayfa < 1 or not 1 <= adet <= 25:
        raise ValueError("İfade, pozitif sayfa ve 1–25 arasında adet gereklidir.")
    data = await _records({"query":ifade,"page":sayfa,"size":adet})
    return {"toplam":data.get("total"), "sayfa":sayfa, "sonuclar":[_card(r) for r in data["data"]]}


async def _decision(identifier):
    if re.fullmatch(r"[0-9]{4}/[0-9]+", identifier):
        matches = (await _records({"basvuruNo":identifier,"page":1,"size":5}))["data"]
        exact = [r for r in matches if r.get("basvuruNo")==identifier]
        if len(exact)!=1:
            raise LookupError("Başvuru numarası tek bir kararla doğrulanamadı.")
        identifier = exact[0]["id"]
    identifier = str(uuid.UUID(identifier))
    rows = (await _records({"id":identifier,"page":1,"size":1}))["data"]
    if len(rows)!=1 or rows[0].get("id")!=identifier or not rows[0].get("icerik"):
        raise LookupError("AYM karar kimliği veya tam metin doğrulanamadı.")
    return rows[0]


def _paras(html):
    # Yalnızca kaynak HTML'deki numaralı paragraf bloklarını kabul et.
    items = {}
    blocks = BeautifulSoup(html,"html.parser").find_all("p")
    lines = [" ".join(p.get_text().split()) for p in blocks]
    start = next((i for i, line in enumerate(lines) if "BAŞVURUNUN KONUSU" in line), len(lines))
    for p, line in zip(blocks[start:], lines[start:]):
        # Word biçimli kararlarda numaralı alt başlıklar da kalın yazılabilir.
        fragments = [v for v in p.find_all(string=True) if v.strip()]
        if fragments and all(v.find_parent(["b", "strong"]) for v in fragments):
            continue
        m = re.match(r"^\s*([0-9]+)\s*\.\s*(.+)$",line,re.S)
        if m:
            items.setdefault(int(m[1]),[]).append(" ".join(m[2].split()))
    return items


async def aym_paragraf_getir(karar_id: str, paragraf_no: int) -> dict:
    """AYM başvuru no veya UUID ile kaynağın açıkça numaralandırdığı paragrafı getirir."""
    row = await _decision(karar_id)
    matches = _paras(row["icerik"]).get(paragraf_no,[])
    if len(matches)!=1:
        raise LookupError("Paragraf bulunamadı veya numara birden fazla bölümde kullanılmış.")
    return {**_card(row),"paragraf":paragraf_no,"metin":matches[0]}


def register(mcp, fetch_yargitay):
    mcp.tool(aym_ara, annotations={"readOnlyHint":True})
    mcp.tool(aym_paragraf_getir, annotations={"readOnlyHint":True})

    @mcp.tool(annotations={"readOnlyHint":True})
    async def emsal_dogrula(onerme: str, karar_id: str, mahkeme: Literal["Yargıtay","AYM"]="Yargıtay",
                            paragraf_no: int | None=None, alinti: str="", degerlendirme: _verdict | None=None,
                            pasaj_sahibi: _role | None=None, gerekce: str="", baslangic: int=0) -> dict:
        """Önce önerme ve karar kimliğiyle çağırıp kararın bütününü oku. AYM için paragraf seç.
        Önermeyi hukuki mesele, olay, hüküm ve pasajın sahibine göre değerlendir.
        Ardından aynı araçta birebir alıntı, değerlendirme, pasaj sahibi ve somut gerekçe gönder.
        Araç kaynaktaki eşleşmeyi doğrular; hukuki değerlendirmeyi istemci yapar.
        İfadeyi tek başına dayanak sayma. AYM paragrafı ve Yargıtay künyesi uydurma."""
        if not onerme.strip() or baslangic < 0:
            raise ValueError("Önerme gereklidir; başlangıç sıfır veya pozitif olmalı.")
        if mahkeme=="AYM":
            if paragraf_no is not None:
                doc = await aym_paragraf_getir(karar_id,paragraf_no)
            else:
                row = await _decision(karar_id)
                doc = {**_card(row),"metin":BeautifulSoup(row["icerik"],"html.parser").get_text(" ",strip=True)}
        else:
            if paragraf_no is not None:
                raise ValueError("Yargıtay için kaynaksız paragraf numarası kullanılamaz.")
            doc = await fetch_yargitay(karar_id, karakter_sayisi=None)
        source_text = " ".join((doc.get("metin") or "").split())
        if mahkeme == "AYM":
            card, card_status = doc, "resmî AYM kaydı"
        else:
            card, card_status = await bedesten.resolve_card(karar_id, source_text)
        info = {"onerme":onerme,"karar_id":karar_id,"mahkeme":mahkeme,"kaynak":doc.get("kaynak"),
                "paragraf":paragraf_no, "kunye_durumu":card_status, "alinti_dogrulandi":False,
                "hukuki_degerlendirme_dogrulanmadi":True, "pasaj_sahibi_dogrulandi":False,
                "kunye":{key:card.get(key) for key in
                         ("daire","esas_no","karar_no","karar_tarihi","basvuru_no","ad")}}

        quote = " ".join(alinti.split())
        if quote:
            # Count overlapping literal matches too, so an ambiguous passage never gets one context.
            count = sum(1 for _ in re.finditer(f"(?={re.escape(quote)})", source_text))
            info.update(alinti_dogrulandi=count > 0, alinti_eslesme_sayisi=count)
            if count == 1:
                start = source_text.index(quote)
                end = start + len(quote)
                info["alinti_baglami"] = {"once":source_text[max(0,start-200):start],
                                         "sonra":source_text[end:end+200]}

        if not source_text:
            return {**info,"durum":"doğrulanamadı","neden":"Karar metni alınamadı."}
        if degerlendirme is None:
            if baslangic >= len(source_text):
                raise ValueError("Başlangıç karar uzunluğunu aşıyor.")
            return {**info,"durum":"inceleme","metin":source_text[baslangic:baslangic+16000],
                    "sonraki_baslangic":baslangic+16000 if baslangic+16000<len(source_text) else None,
                    "talimat":"Kararı ve konuşanı belirle. Destek derecesini, kaynaktan alıntıyı ve gerekçeni bu araca gönder."}
        if mahkeme=="AYM" and paragraf_no is None:
            raise ValueError("AYM atfını doğrulamak için kaynak paragraf numarası gereklidir.")
        if not info["alinti_dogrulandi"] or not gerekce.strip() or not pasaj_sahibi:
            return {**info,"durum":"doğrulanamadı","neden":"Birebir alıntı, pasaj sahibi ve gerekçe doğrulama için gerekli."}
        return {**info,"alinti_kaynakta":True,"alinti":quote,"istemci_degerlendirmesi":degerlendirme,
                "istemcinin_belirledigi_pasaj_sahibi":pasaj_sahibi,"gerekce":gerekce}
