"""Birincil mevzuat servisine erişilemediğinde Adalet Bakanlığı kaynağını kullan."""
import re

import bedesten
from metin import sayfali_belge
from turk_hukuku_mevzuat import registry, server as primary
from turk_hukuku_mevzuat.ortak import ErisimDurdu, KaynakHatasi


async def _search(filters, limit):
    data = await bedesten.search_page("/mevzuat/searchDocuments", {
        "mevzuatTurList": ["KANUN"], "pageNumber": 1, "pageSize": limit, **filters,
    }, "mevzuatList")
    return bedesten.rows(data, "mevzuatList"), data["total"]


def _card(row):
    if row["mevzuatTur"]["id"] != 1 or not row.get("mevzuatTertip"):
        raise LookupError("Bedesten kanun türü veya tertibi doğrulanamadı.")
    return {"ad": row["mevzuatAdi"], "no": str(row["mevzuatNo"]),
            "mevzuat_id": f"1.{row['mevzuatTertip']}.{row['mevzuatNo']}",
            "tur": "KANUN", "kabul_tarihi": row.get("kabulTarihi"),
            "resmi_gazete": row.get("resmiGazeteTarihi"),
            "kaynak": f"{bedesten.SITE}/mevzuat/{row['mevzuatId']}"}


async def _resolve(kanun):
    identity, _, number = registry.cozumle(kanun)
    records, _ = await _search({"mevzuatNo": number}, 20)
    matches = [row for row in records if _card(row)["mevzuat_id"] == identity]
    if len(matches) != 1:
        raise LookupError(f"Bedesten üzerinde kanun tekil olarak doğrulanamadı: {identity}")
    row = matches[0]
    card = _card(row)
    return str(row["mevzuatId"]), {"kanun": card["ad"], "mevzuat_id": identity, "kaynak": card["kaynak"]}


async def mevzuat_ara(ifade: str, nerede: str = "Baslik", adet: int = 10) -> dict:
    """Kanunları başlıkta (Baslik), içerikte (Icerik) veya ikisinde (Tumu) ara."""
    if nerede not in ("Baslik", "Icerik", "Tumu") or not ifade.strip():
        raise ValueError("Arama ifadesi ve Baslik/Icerik/Tumu alanı gereklidir.")
    try:
        return await primary.mevzuat_ara(ifade, nerede, adet)
    except (KaynakHatasi, ErisimDurdu):
        pass
    limit = max(1, min(50, adet))
    fields = {"Baslik": ["mevzuatAdi"], "Icerik": ["phrase"], "Tumu": ["mevzuatAdi", "phrase"]}
    cards = {}
    complete = True
    for field in fields[nerede]:
        rows, total = await _search({field: ifade}, limit)
        complete = complete and len(rows) == total
        for row in rows:
            card = _card(row)
            cards[card["mevzuat_id"]] = card
    # İki kısmi listenin ortak belge sayısı kaynaktan öğrenilemiyor.
    count = total if nerede != "Tumu" else (len(cards) if complete else None)
    return {"ifade": ifade, "nerede": nerede, "toplam": count, "sonuclar": list(cards.values())[:limit],
            "kaynak": bedesten.SITE}


async def kanun_metni_getir(kanun: str, baslangic: int = 0, karakter_sayisi: int | None = None) -> dict:
    """Kanunu numara, kısaltma veya tam kimlikle oku. Tek madde için mevzuat_madde_getir kullan.
    İlk incelemede karakter_sayisi=4000, devamında sonraki_baslangic kullan. Sınır verilmezse tam metin döner."""
    try:
        belge = await primary.kanun_metni_getir(kanun)
    except (KaynakHatasi, ErisimDurdu):
        doc, card = await _resolve(kanun)
        text = await bedesten.document(doc, law=True)
        belge = {**card, "uzunluk": len(text), "metin": text}
    return sayfali_belge(belge, baslangic, karakter_sayisi)


def _article_ids(node, doc, number):
    for child in node["children"]:
        label = child.get("maddeBaslik") or ""
        if (str(child.get("mevzuatId")) == doc and child.get("maddeNo") == number
                and re.match(rf"^Madde No:\s*{number}(?:\s*-|$)", label, re.I)):
            yield str(child["maddeId"])
        yield from _article_ids(child, doc, number)


async def madde_getir(kanun: str, madde_no: int) -> dict:
    """Belirtilen kanunun numaralı maddesini kaynak bağlantısıyla getir."""
    if madde_no < 1:
        raise ValueError("Madde numarası pozitif olmalı.")
    try:
        return await primary.madde_getir(kanun, madde_no)
    except (KaynakHatasi, ErisimDurdu):
        pass
    doc, card = await _resolve(kanun)
    tree = await bedesten.request("/mevzuat/mevzuatMaddeTree", {"mevzuatId": doc})
    ids = list(_article_ids(tree, doc, madde_no))
    if len(ids) > 1:
        raise LookupError("Aynı numaralı birden fazla madde var.")
    text = await bedesten.document(ids[0], article=True) if ids else None
    return {**card, "madde_no": madde_no, "metin": text,
            "atif": f"{card['kanun']} m.{madde_no} (kaynak: {card['kaynak']})",
            "uyari": None if text else "Numaralı madde Bedesten dizininde bulunamadı."}
