"""Canlı MCP denetimi: python test_live.py YYYY-MM-DD (erişilebilir RG sayısı)."""
import asyncio
import sys
from datetime import date

from fastmcp import Client
from server import mcp


async def audit(client, issue):
    tested = set()

    async def call(name, **params):
        result = await client.call_tool(name, params)
        tested.add(name)
        print(name, flush=True)
        return result.data

    assert "Bedesten" in await call("kaynak_durumu")
    assert "Ceza Genel Kurulu" in (await call("yargitay_daire_listesi"))["daireler"]
    assert (await call("yargitay_baglanti_testi"))["ilk"]
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
    index = await call("resmi_gazete_fihrist", tarih=issue, ikincil_kaynak=True)
    publication = await call("resmi_gazete_belgesi", belge=index["belgeler"][0]["belge"])
    assert index["tarih"] == issue and publication["metin"].strip()
    judgments = await call("aihm_ara", ifade="reasonable suspicion", ulke="TUR", adet=1)
    item = judgments["sonuclar"][0]
    judgment = await call("aihm_karar_getir", karar_id=item["itemid"])
    assert judgment["id"] == item["itemid"] and judgment["metin"].strip()
    theses = await call("yoktez_ara", ifade="makul süre", adet=1)
    item = theses["sonuclar"][0]
    detail = await call("yoktez_detay", kayit=item["kayit"], belge=item["belge"])
    assert detail["trOzet"] or detail["enOzet"]
    assert tested == {tool.name for tool in await client.list_tools()}
    print(f"{len(tested)} araç geçti.")


async def main():
    async with Client(mcp) as client:
        await audit(client, sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat())


if __name__ == "__main__":
    asyncio.run(main())
