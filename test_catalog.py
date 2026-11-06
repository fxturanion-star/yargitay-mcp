import unittest
from unittest.mock import AsyncMock, patch
from fastmcp import Client
import server


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_and_compatibility_dispatch(self):
        result = {"durum":"deneysel", "sonuclar":[]}
        with patch.object(server, "_semantik_arama", AsyncMock(return_value=result)) as semantic:
            async with Client(server.mcp) as client:
                catalog = (await client.call_tool("yargitay_baglanti_testi", {"arac_listesi":True})).data
                self.assertEqual(catalog["arac_sayisi"], 22)
                self.assertIn("semantik_ictihat_ara", catalog["araclar"])
                response = await client.call_tool("yargitay_toplu_arastirma", {
                    "aranan_kelime":"Kolluğun soyut şüphesiyle konutta arama", "daire":"Ceza Genel Kurulu",
                    "metin_bicimi":"semantik", "metin_sayisi":3, "sonuc_sayisi":2})
                self.assertEqual(response.data, result)
                semantic.assert_awaited_once_with(soru="Kolluğun soyut şüphesiyle konutta arama",
                    daire="Ceza Genel Kurulu", baslangic_tarihi="", bitis_tarihi="", aday_sayisi=3, sonuc_sayisi=2)
