"""Canlı MCP denetimi: python test_live.py YYYY-MM-DD (erişilebilir RG sayısı)."""
import asyncio
import sys
import kaynaklar
from datetime import date

from fastmcp import Client
from fastmcp.exceptions import ToolError
from server import mcp


async def audit(client, issue):
    tested = set()

    async def call(name, **params):
        try:
            result = await client.call_tool(name, params)
        except ToolError:
            # Bedesten 429 için kaynağın bildirdiği süreyi yalnızca bir kez bekle.
            if name not in {"emsal_dogrula", "yargitay_karar_ara", "yargitay_karar_metni",
                            "yargitay_toplu_arastirma", "yargitay_baglanti_testi"}:
                raise
            health = (await client.call_tool("kaynak_durumu", {})).data["Bedesten"]
            wait = health["bekleme_saniye"]
            if health["son_http_durumu"] != "HTTP 429" or not 0 < wait <= 120:
                raise
            print(f"Bedesten HTTP 429; {wait} saniye bekleniyor: {name}", flush=True)
            await asyncio.sleep(wait + 1)
            result = await client.call_tool(name, params)
        tested.add(name)
        print(name, flush=True)
        return result.data

    assert "Bedesten" in await call("kaynak_durumu")
    assert "Ceza Genel Kurulu" in (await call("yargitay_daire_listesi"))["daireler"]
    # Bilinen bir resmî belgeyi süreç başlangıcında, önce aramadan çöz.
    samples = [
        ("75719900", "Ceza Genel Kurulu", "2011/245", "2012/61", "28.02.2012"),
        ("109227200", "4. Hukuk Dairesi", "2014/15489", "2015/12166", "02.11.2015"),
        ("631834100", "9. Hukuk Dairesi", "2020/9097", "2021/848", "14.01.2021"),
        ("1018167800", "1. Ceza Dairesi", "2022/8669", "2024/1416", "04.03.2024"),
    ]
    for identifier, court, case, decision, day in samples:
        await asyncio.sleep(8)
        cold = await call("emsal_dogrula", karar_id="bedesten:"+identifier, onerme="Karar künyesini incele")
        actual = cold["kunye"]
        assert (actual["daire"], actual["esas_no"], actual["karar_no"], actual["karar_tarihi"]) == (court, case, decision, day)
        assert "E./K. doğrulandı" in cold["kunye_durumu"]
        print("Künye:", identifier, actual, flush=True)
    assert (await call("yargitay_baglanti_testi"))["ilk"]
    for court in ("Ceza Genel Kurulu", "1. Ceza Dairesi"):
        newest = await call("yargitay_karar_ara", daire=court, sayfa_boyutu=3, en_yeni=True)
        assert newest["tarih_olcutu"] == "karar_tarihi" and newest["indekse_eklenme_sirasi_dogrulandi"] is False
        assert len(newest["kararlar"]) == 3 and all(row["daire"] == court for row in newest["kararlar"])
        print(court, [(row["karar_tarihi"], row["karar_no"]) for row in newest["kararlar"]], flush=True)
    search = await call("yargitay_karar_ara", daire="Ceza Genel Kurulu", sayfa_boyutu=1)
    doc = search["kararlar"][0]["id"]
    assert search["kararlar"][0]["daire"] == "Ceza Genel Kurulu"
    assert (await call("yargitay_karar_metni", karar_id=doc))["metin"].strip()
    assert (await call("yargitay_toplu_arastirma", aranan_kelime='"makul şüphe"',
                       sonuc_sayisi=1, metin_sayisi=1))["kararlar"]
    assert (await call("emsal_dogrula", onerme="Kararın gerekçesini incele", karar_id=doc))["durum"] == "inceleme"

    assert any(r["no"] == 5271 for r in await call("mevzuat_bilinen_kanunlar"))
    laws = await call("mevzuat_ara", ifade="Ceza Muhakemesi Kanunu", adet=50)
    assert any(r["mevzuat_id"] == "1.5.5271" for r in laws["sonuclar"])
    article = await call("mevzuat_madde_getir", kanun="CMK", madde_no=116)
    assert article["mevzuat_id"] == "1.5.5271" and "makul şüphe" in " ".join(article["metin"].split()).lower()
    full = await call("mevzuat_kanun_metni_getir", kanun="5271")
    assert full["uzunluk"] == len(full["metin"]) > 10000
    documents = await call("mevzuat_genel_ara", ifade="", tur="KKY", adet=1)
    regulation = await call("mevzuat_belgesi_getir", belge_id=documents["sonuclar"][0]["id"])
    assert regulation["metin"].strip()

    decisions = await call("aym_ara", ifade='"makul şüphe"', adet=1)
    item = decisions["sonuclar"][0]
    para = await call("aym_paragraf_getir", karar_id=item["basvuru_no"], paragraf_no=1)
    assert para["id"] == item["id"] and para["metin"].strip()
    judgments = await call("aihm_ara", ifade="reasonable suspicion", ulke="TUR", adet=1)
    item = judgments["sonuclar"][0]
    judgment = await call("aihm_karar_getir", karar_id=item["itemid"])
    assert judgment["id"] == item["itemid"] and judgment["metin"].strip()
    theses = await call("yoktez_ara", ifade="makul süre", adet=1)
    item = theses["sonuclar"][0]
    detail = await call("yoktez_detay", kayit=item["kayit"], belge=item["belge"])
    assert detail["trOzet"] or detail["enOzet"]
    assert tested | {"resmi_gazete_fihrist", "resmi_gazete_belgesi"} == {tool.name for tool in await client.list_tools()}
    print(f"{len(tested)} araç geçti.")


async def audit_rg(client, day, secondary):
    # İki bağımsız çağrı: bir kaynağın başarısı diğerinin erişimini maskelemez.
    if secondary:
        index = await kaynaklar.lexpera_fihrist(day)
    else:
        index = (await client.call_tool("resmi_gazete_fihrist",
                 {"tarih":day,"ikincil_kaynak":False})).data
    assert index["tarih"] == day and index["resmi_kaynak"] is (not secondary)
    print("Fihrist:", index["kaynak"], flush=True)
    item = index["belgeler"][0]
    doc = (await client.call_tool("resmi_gazete_belgesi", {"belge":item["belge"]})).data
    assert doc["resmi_kaynak"] is (not secondary) and doc["kaynak"] == item["kaynak"] and doc["metin"].strip()
    print("Belge:", doc["kaynak"], "karakter:", len(doc["metin"]), flush=True)


async def main():
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    mode = sys.argv[2] if len(sys.argv) > 2 else "core"
    async with Client(mcp) as client:
        if mode == "core":
            await audit(client, day)
        elif mode in ("resmi", "lexpera"):
            await audit_rg(client, day, secondary=mode == "lexpera")
        else:
            raise ValueError("Test modu core, resmi veya lexpera olmalı.")


if __name__ == "__main__":
    asyncio.run(main())
