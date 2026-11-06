"""Yargıtay araştırması (Bedesten), mevzuat ve resmî belge araçları."""
from __future__ import annotations

import os
import re
from typing import Any

from fastmcp import FastMCP
import bedesten

# Geçerli daire adları (birimYrgKurulDaire alanı için)
DAIRELER: list[str] = (
    ["Büyük Genel Kurulu", "Hukuk Genel Kurulu", "Ceza Genel Kurulu",
     "Hukuk Daireleri Başkanlar Kurulu", "Ceza Daireleri Başkanlar Kurulu"]
    + [f"{i}. Hukuk Dairesi" for i in range(1, 24)]
    + [f"{i}. Ceza Dairesi" for i in range(1, 24)]
)

mcp = FastMCP(
    name="Yargıtay Karar Arama",
    instructions=(
        "Adalet Bakanlığı Bedesten üzerinde Yargıtay kararı arar ve karar "
        "tam metnini getirir. Önce yargitay_karar_ara ile arama yapın, "
        "sonuçtaki 'id' değerini yargitay_karar_metni aracına verin. "
        "Kaynak sitede hız sınırı vardır; araçlar istekleri otomatik "
        "yavaşlatır — art arda çok sayıda çağrıdan kaçının."
    ),
)


# Karar metni önbelleği (id -> düz metin). Aynı oturumda tekrar istenen
# kararlar siteye gidilmeden döner.
_CACHE_MAX = int(os.environ.get("YARGITAY_CACHE_MAX", "500"))
_doc_cache: dict[str, str] = {}


def _cache_put(karar_id: str, text: str) -> None:
    if len(_doc_cache) >= _CACHE_MAX:
        _doc_cache.pop(next(iter(_doc_cache)))
    _doc_cache[karar_id] = text


def _keyword_windows(text: str, keyword: str, window: int = 700, max_hits: int = 4) -> str:
    """Metinde aranan ifadenin geçtiği bölgeleri (±window karakter) döndürür."""
    if not keyword:
        return text[: 2 * window]
    core = keyword.replace('"', "").strip()
    terms = [t for t in re.split(r"\s+", core) if len(t) > 2] or [core]
    pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
    spans: list[tuple[int, int]] = []
    for m in pattern.finditer(text):
        start, end = max(0, m.start() - window), min(len(text), m.end() + window)
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
        if len(spans) >= max_hits:
            break
    if not spans:
        return text[: 2 * window]
    parts = [("…" if s > 0 else "") + text[s:e] + ("…" if e < len(text) else "") for s, e in spans]
    return "\n[...]\n".join(parts)


async def _fetch_doc_text(karar_id: str) -> str:
    """Karar metnini önbellekten veya siteden getirir."""
    if karar_id in _doc_cache:
        return _doc_cache[karar_id]
    if karar_id.startswith("bedesten:"):
        text = await bedesten.document(karar_id.removeprefix("bedesten:"))
        _cache_put(karar_id, text)
        return text
    raise ValueError("Eski Yargıtay kimliği: kararı E./K. ile tekrar arayıp bedesten: kimliğini kullanın.")


def _validate_date(value: str, name: str) -> None:
    if value and not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", value):
        raise ValueError(f"{name} GG.AA.YYYY formatında olmalıdır (örn. 01.01.2024).")


@mcp.tool
async def yargitay_daire_listesi() -> dict:
    """Yargıtay karar aramasında kullanılabilecek geçerli daire/kurul adlarını döndürür.

    yargitay_karar_ara aracının 'daire' parametresine bu listeden bir değer verin.
    """
    return {"daireler": DAIRELER}


async def _do_search(
    aranan_kelime: str = "",
    daire: str = "",
    esas_yil: str = "",
    esas_ilk_sira_no: str = "",
    esas_son_sira_no: str = "",
    karar_yil: str = "",
    karar_ilk_sira_no: str = "",
    karar_son_sira_no: str = "",
    baslangic_tarihi: str = "",
    bitis_tarihi: str = "",
    sayfa: int = 1,
    sayfa_boyutu: int = 10,
) -> dict:
    """Yargıtay kararlarında detaylı arama yapar (Adalet Bakanlığı Bedesten).

    Args:
        aranan_kelime: Aranacak kelime/ifade. Kesin ifade için çift tırnak
            kullanın: "elektrik piyasası". Boş bırakılıp yalnızca
            daire/esas/karar/tarih filtreleriyle de arama yapılabilir.
        daire: Daire/kurul adı (örn. "3. Hukuk Dairesi", "Hukuk Genel Kurulu").
            Boş bırakılırsa tüm dairelerde arar. Geçerli adlar için
            yargitay_daire_listesi aracını kullanın.
        esas_yil: Esas yılı (YYYY).
        esas_ilk_sira_no: Esas ilk sıra no (aralık başlangıcı).
        esas_son_sira_no: Esas son sıra no (aralık sonu).
        karar_yil: Karar yılı (YYYY).
        karar_ilk_sira_no: Karar ilk sıra no.
        karar_son_sira_no: Karar son sıra no.
        baslangic_tarihi: Karar tarihi aralığı başlangıcı, GG.AA.YYYY.
        bitis_tarihi: Karar tarihi aralığı sonu, GG.AA.YYYY.
        sayfa: Sonuç sayfası (1'den başlar).
        sayfa_boyutu: Sayfa başına sonuç (1-100).

    Returns:
        toplam_sonuc ve kararlar listesi (id, daire, esas_no, karar_no,
        karar_tarihi). Tam metin için id'yi yargitay_karar_metni aracına verin.
    """
    _validate_date(baslangic_tarihi, "baslangic_tarihi")
    _validate_date(bitis_tarihi, "bitis_tarihi")
    if daire:
        if daire.strip().upper() == "ALL":
            daire = ""
        elif daire not in DAIRELER:
            raise ValueError(
                f"Geçersiz daire adı: {daire!r}. "
                "Geçerli adlar için yargitay_daire_listesi aracını çağırın."
            )
    sayfa = max(1, int(sayfa))
    sayfa_boyutu = min(100, max(1, int(sayfa_boyutu)))

    data: dict[str, Any] = {
        "aranan": aranan_kelime or "",

        "pageSize": sayfa_boyutu,
        "pageNumber": sayfa,
    }
    # Boş filtre alanlarını hiç gönderme; "ALL" değeri 0 sonuç döndürüyor.
    if daire:
        data["birimYrgKurulDaire"] = daire
    for key, val in {
        "esasYil": esas_yil, "esasIlkSiraNo": esas_ilk_sira_no,
        "esasSonSiraNo": esas_son_sira_no, "kararYil": karar_yil,
        "kararIlkSiraNo": karar_ilk_sira_no, "kararSonSiraNo": karar_son_sira_no,
        "baslangicTarihi": baslangic_tarihi, "bitisTarihi": bitis_tarihi,
    }.items():
        if val:
            data[key] = str(val)

    return await bedesten.judgments(data)


@mcp.tool
async def yargitay_karar_ara(
    aranan_kelime: str = "",
    daire: str = "",
    esas_yil: str = "",
    esas_ilk_sira_no: str = "",
    esas_son_sira_no: str = "",
    karar_yil: str = "",
    karar_ilk_sira_no: str = "",
    karar_son_sira_no: str = "",
    baslangic_tarihi: str = "",
    bitis_tarihi: str = "",
    sayfa: int = 1,
    sayfa_boyutu: int = 10,
) -> dict:
    """Yargıtay kararlarında detaylı arama yapar (yalnızca künye listesi döner).

    Metinlerle birlikte TOPLU araştırma için yargitay_toplu_arastirma aracını
    tercih edin — çok daha hızlıdır (tek çağrıda arama + metinler).

    Args:
        aranan_kelime: Aranacak kelime/ifade. Kesin ifade için çift tırnak:
            "elektrik piyasası".
        daire: Daire/kurul adı (örn. "3. Hukuk Dairesi", "Hukuk Genel Kurulu").
            Boş bırakılırsa tüm daireler. Geçerli adlar: yargitay_daire_listesi.
        esas_yil: Esas yılı (YYYY).
        esas_ilk_sira_no: Esas ilk sıra no.
        esas_son_sira_no: Esas son sıra no.
        karar_yil: Karar yılı (YYYY).
        karar_ilk_sira_no: Karar ilk sıra no.
        karar_son_sira_no: Karar son sıra no.
        baslangic_tarihi: Karar tarihi aralığı başlangıcı, GG.AA.YYYY.
        bitis_tarihi: Karar tarihi aralığı sonu, GG.AA.YYYY.
        sayfa: Sonuç sayfası (1'den başlar).
        sayfa_boyutu: Sayfa başına sonuç (1-100).
    """
    return await _do_search(
        aranan_kelime, daire, esas_yil, esas_ilk_sira_no, esas_son_sira_no,
        karar_yil, karar_ilk_sira_no, karar_son_sira_no,
        baslangic_tarihi, bitis_tarihi, sayfa, sayfa_boyutu,
    )


@mcp.tool
async def yargitay_toplu_arastirma(
    aranan_kelime: str,
    daire: str = "",
    baslangic_tarihi: str = "",
    bitis_tarihi: str = "",
    sonuc_sayisi: int = 30,
    metin_sayisi: int = 5,
    metin_bicimi: str = "pencere",
) -> dict:
    """TEK ÇAĞRIDA emsal araştırması: arama + ilk N kararın metni birlikte döner.

    Karar karar ayrı çağrı yapmak yerine bunu kullanın — sunucu metinleri
    kendi içinde (hız sınırına uyarak) toplar ve tek pakette döndürür.
    Önbellek sayesinde tekrarlanan kararlar anında gelir.

    Args:
        aranan_kelime: Aranacak kelime/ifade. Kesin ifade için çift tırnak:
            "elektrik piyasası". Zorunlu.
        daire: Daire/kurul adı (boş = tüm daireler).
        baslangic_tarihi: Karar tarihi aralığı başlangıcı, GG.AA.YYYY.
        bitis_tarihi: Karar tarihi aralığı sonu, GG.AA.YYYY.
        sonuc_sayisi: Künyesi listelenecek karar sayısı (1-100, varsayılan 30).
        metin_sayisi: Metni getirilecek karar sayısı (0-10, varsayılan 5).
            Not: her metin kaynak siteden ~3 sn sürer; 10 metin ≈ 30 sn.
        metin_bicimi: "pencere" = aranan ifadenin geçtiği bölümler (varsayılan,
            önerilen — pakete daha çok karar sığar) | "tam" = kararın tamamı.

    Returns:
        toplam_sonuc, kararlar (künye listesi) ve metinler (id + metin).
    """
    if not aranan_kelime.strip():
        raise ValueError("aranan_kelime boş olamaz.")
    sonuc_sayisi = min(100, max(1, int(sonuc_sayisi)))
    metin_sayisi = min(10, max(0, int(metin_sayisi)))
    if metin_bicimi not in ("pencere", "tam"):
        raise ValueError('metin_bicimi "pencere" veya "tam" olmalıdır.')

    arama = await _do_search(
        aranan_kelime=aranan_kelime, daire=daire,
        baslangic_tarihi=baslangic_tarihi, bitis_tarihi=bitis_tarihi,
        sayfa=1, sayfa_boyutu=sonuc_sayisi,
    )
    metinler = []
    hatalar = []
    for k in arama["kararlar"][:metin_sayisi]:
        try:
            text = await _fetch_doc_text(k["id"])
        except Exception as e:  # tek karar hatası araştırmayı durdurmasın
            hatalar.append(f"{k['id']}: {type(e).__name__}")
            continue
        metinler.append({
            "id": k["id"],
            "daire": k["daire"],
            "esas_no": k["esas_no"],
            "karar_no": k["karar_no"],
            "karar_tarihi": k["karar_tarihi"],
            "metin": _keyword_windows(text, aranan_kelime) if metin_bicimi == "pencere" else text,
        })
    out = {
        "toplam_sonuc": arama["toplam_sonuc"],
        "kararlar": arama["kararlar"],
        "metinler": metinler,
        "metin_bicimi": metin_bicimi,
    }
    if hatalar:
        out["hatalar"] = hatalar
    if arama["toplam_sonuc"] > sonuc_sayisi:
        out["not"] = (
            f"Toplam {arama['toplam_sonuc']} sonuçtan ilk {sonuc_sayisi} künye "
            "listelendi. Daraltmak için daire/tarih filtresi veya daha spesifik "
            "ifade kullanın."
        )
    return out


@mcp.tool
async def yargitay_karar_metni(karar_id: str) -> dict:
    """Bir Yargıtay kararının tam metnini getirir.

    Args:
        karar_id: yargitay_karar_ara sonucundaki 'id' değeri.

    Returns:
        Kararın düz metin hâli ve kaynak URL'si.
    """
    karar_id = str(karar_id).strip()
    if not re.fullmatch(r"(?:bedesten:)?[0-9]{1,20}", karar_id):
        raise ValueError("karar_id sayısal bir kimlik olmalıdır (arama sonucundaki 'id').")
    text = await _fetch_doc_text(karar_id)
    if not text:
        return {
            "id": karar_id,
            "metin": "",
            "uyari": "Belge boş döndü; id geçersiz veya belge kaldırılmış olabilir.",
        }
    return {
        "id": karar_id,
        "kaynak": f"{bedesten.SITE}/ictihat/{karar_id.removeprefix('bedesten:')}",
        "metin": text,
    }

mcp.tool(bedesten.mevzuat_genel_ara)
mcp.tool(bedesten.mevzuat_belgesi_getir)

from turk_hukuku_mevzuat import server as mevzuat_modulu

mcp.tool(
    mevzuat_modulu.madde_getir,
    name="mevzuat_madde_getir",
)
mcp.tool(
    mevzuat_modulu.kanun_metni_getir,
    name="mevzuat_kanun_metni_getir",
)
mcp.tool(
    mevzuat_modulu.mevzuat_ara,
    name="mevzuat_ara",
)
mcp.tool(
    mevzuat_modulu.bilinen_kanunlar,
    name="mevzuat_bilinen_kanunlar",
)
@mcp.tool(annotations={"readOnlyHint": True})
async def yargitay_baglanti_testi() -> dict:
    """Etkin kaynak Bedesten üzerinde bir sonuçluk gerçek CGK araması yapar."""
    sonuc = await _do_search(daire="Ceza Genel Kurulu", sayfa_boyutu=1)
    return {"kaynak": sonuc["kaynak"], "toplam": sonuc["toplam_sonuc"], "ilk": sonuc["kararlar"]}

import kaynaklar
kaynaklar.register(mcp)

import emsal
emsal.register(mcp, yargitay_karar_metni)

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "http")
    if transport == "stdio":
        mcp.run()
    else:
        mcp.run(
            transport="http",
            host="0.0.0.0",
            port=int(os.environ.get("PORT", "8000")),
            path=os.environ.get("MCP_PATH", "/mcp"),
        )
