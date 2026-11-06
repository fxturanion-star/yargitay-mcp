"""Kapalı ağda MCP sınırını, yeniden sıralamayı ve kaynak konumlarını denetler."""
import unittest
from unittest.mock import AsyncMock, patch

from fastmcp import Client, FastMCP

import bedesten
import semantik


def card(number):
    return {"id":f"bedesten:{number}", "daire":"1. Ceza Dairesi", "esas_no":f"2023/{number}",
            "karar_no":f"2024/{number}", "karar_tarihi":"12.03.2024",
            "kaynak":f"https://mevzuat.adalet.gov.tr/ictihat/{number}"}


class SemanticToolTests(unittest.IsolatedAsyncioTestCase):
    def app(self, search, read):
        app = FastMCP("test")
        semantik.register(app, search, read)
        return app

    async def test_reranking_deduplication_filters_and_verbatim_offset(self):
        cards = [card("101"), card("102"), card("103")]
        texts = {
            "bedesten:101": "1. Ceza Dairesi 2023/101 E., 2024/101 K. Konut aramasında vekâlet ücretinin miktarı incelendi.",
            "bedesten:102": "1. Ceza Dairesi 2023/102 E., 2024/102 K. Konut araması için somut emare yoktur.\n  İhbar denetlenmemiştir.",
            "bedesten:103": "1. Ceza Dairesi 2023/103 E., 2024/103 K. Ölüm kaydı incelendi.",
        }
        searches = AsyncMock(return_value={"kararlar":cards,"toplam_sonuc":len(cards)})
        read = AsyncMock(side_effect=lambda key:texts[key])
        def scorer(question, passages):
            return [0.85 if "emare" in passage else 0.2 for passage in passages]
        with (patch.object(semantik, "similarities", side_effect=scorer),
              patch.object(bedesten, "_kunyeler", {c["id"]:c for c in cards}),
              patch.object(bedesten, "request", side_effect=AssertionError("Ağsız testte kaynak çağrısı"))):
            async with Client(self.app(searches, read)) as client:
                data = (await client.call_tool("semantik_ictihat_ara", {
                    "soru":"Kişisel kanaat evin aranmasını haklı kılar mı?",
                    "arama_ifadeleri":["arama","ihbar"], "daire":"1. Ceza Dairesi",
                    "baslangic_tarihi":"01.01.2024", "bitis_tarihi":"31.12.2024",
                    "aday_sayisi":3,"sonuc_sayisi":2})).data
        results = data["sonuclar"]
        self.assertEqual([r["id"] for r in results], ["bedesten:102", "bedesten:101"])
        self.assertEqual(read.await_count, 3)
        self.assertEqual(data["odak_disi_pasaj"], 1)
        self.assertGreater(results[0]["benzerlik"], results[1]["benzerlik"])
        for r in results:
            self.assertEqual(r["pasaj"], texts[r["id"]][r["baslangic"]:r["bitis"]])
            self.assertIn(r["kaynak"], {c["kaynak"] for c in cards})
        self.assertTrue(data["kapsam"])
        self.assertFalse(data["hukuki_uygunluk_dogrulandi"])
        self.assertFalse(data["pasaj_sahibi_dogrulandi"])
        for call in searches.await_args_list:
            self.assertEqual(call.kwargs["daire"], "1. Ceza Dairesi")
            self.assertEqual(call.kwargs["baslangic_tarihi"], "01.01.2024")
            self.assertEqual(call.kwargs["bitis_tarihi"], "31.12.2024")

    async def test_empty_search_skips_document_and_embedding_calls(self):
        search = AsyncMock(return_value={"kararlar":[],"toplam_sonuc":0})
        read = AsyncMock()
        with patch.object(semantik, "similarities") as scorer:
            async with Client(self.app(search, read)) as client:
                data = (await client.call_tool("semantik_ictihat_ara", {
                    "soru":"Sorgulanan araştırma konusu", "arama_ifadeleri":["bulunamayan ifade"]})).data
        self.assertEqual(data["sonuclar"], [])
        read.assert_not_awaited()
        scorer.assert_not_called()

    async def test_unreadable_candidates_are_not_silent(self):
        search = AsyncMock(return_value={"kararlar":[card("101"), card("102")],"toplam_sonuc":2})
        read = AsyncMock(side_effect=[ValueError("eksik belge"),
                                      "1. Ceza Dairesi 2023/102 E., 2024/102 K. Metin okunabildi."])
        params = {"soru":"Somut belirtiler gerekli midir?", "arama_ifadeleri":["şüphe"]}
        with (patch.object(semantik, "similarities", return_value=[0.25]),
              patch.object(bedesten, "_kunyeler", {"bedesten:102":card("102")})):
            async with Client(self.app(search, read)) as client:
                partial = (await client.call_tool("semantik_ictihat_ara", params)).data
                self.assertEqual([c["id"] for c in partial["sonuclar"]], ["bedesten:102"])
                self.assertEqual([e["id"] for e in partial["hatalar"]], ["bedesten:101"])
                read.side_effect = ValueError("kaynak erişilemiyor")
                reply = await client.call_tool("semantik_ictihat_ara", params, raise_on_error=False)
                self.assertTrue(reply.is_error)

    async def test_high_scoring_passage_with_conflicting_header_is_excluded(self):
        cards = [card("101"), card("102")]
        texts = {"bedesten:101": "1. Ceza Dairesi 2020/999 E., 2024/101 K. Soyut kanaat yeterli mi?",
                 "bedesten:102": "1. Ceza Dairesi 2023/102 E., 2024/102 K. İhbardan sonra araştırma yapıldı."}
        search = AsyncMock(return_value={"kararlar":cards, "toplam_sonuc":2})
        read = AsyncMock(side_effect=lambda key:texts[key])
        def score(question, passages):
            return [1.0 if "Soyut kanaat" in p else 0.5 for p in passages]
        with (patch.object(semantik, "similarities", side_effect=score),
              patch.object(bedesten, "_kunyeler", {c["id"]:c for c in cards})):
            async with Client(self.app(search, read)) as client:
                result = (await client.call_tool("semantik_ictihat_ara", {
                    "soru":"Soyut kanaat yeterli mi?", "arama_ifadeleri":["kanaat"]})).data
        self.assertEqual([c["id"] for c in result["sonuclar"]], ["bedesten:102"])
        self.assertEqual([e["id"] for e in result["hatalar"]], ["bedesten:101"])
        self.assertIn("uyuşmuyor", result["hatalar"][0]["neden"])

    async def test_invalid_input_makes_no_source_request(self):
        search, read = AsyncMock(), AsyncMock()
        async with Client(self.app(search, read)) as client:
            for args in ({"soru":" "},{"soru":"Soru metni", "aday_sayisi":7},
                         {"soru":"Soru metni", "sonuc_sayisi":0}):
                with self.subTest(args=args):
                    reply = await client.call_tool("semantik_ictihat_ara", args, raise_on_error=False)
                    self.assertTrue(reply.is_error)
        search.assert_not_awaited()
        read.assert_not_awaited()
