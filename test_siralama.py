import unittest
from unittest.mock import AsyncMock, patch

from fastmcp import Client
import bedesten
import server


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_newer_record_missing_is_not_certified(self):
        params = {"kararTarihiEnd":"2026-11-06T23:59:59", "pageSize":2}
        def row(doc, day):
            return {"documentId":doc, "kararTarihiStr":day}
        top = {"total":100,"emsalKararList":[row(1,"19.10.2026"),row(2,"18.10.2026")]}
        newer = {"total":2, "emsalKararList":[row(3,"20.10.2026"),row(1,"19.10.2026")]}
        with patch.object(bedesten,"request",AsyncMock(return_value=newer)):
            with self.assertRaisesRegex(ValueError, "Daha yeni"):
                await bedesten._verify_latest(params,top)

    async def test_cold_id_mismatch(self):
        card = {"id":"bedesten:2","esas_no":"2025/1","karar_no":"2026/2","daire":"Ceza Genel Kurulu"}
        with patch.object(bedesten, "_kunyeler", {}), patch.object(bedesten, "judgments",
                AsyncMock(return_value={"kararlar":[card]})):
            result, note = await bedesten.resolve_card("bedesten:1","Ceza Genel Kurulu 2025/1 E., 2026/2 K.")
        self.assertEqual(result, {})
        self.assertIn("doğrulanamadı", note)

    async def test_quote_roles_are_not_certified(self):
        sections = {"mahkemenin gerekçesi":"Çoğunluk delili yeterli gördü.",
                    "karşıoy":"Delili yeterli görmüyorum.", "başka karardan alıntı":"Önceki kararda böyle denildi."}
        text = " ".join(sections.values())
        with patch.object(server, "_fetch_doc_text", AsyncMock(return_value=text)):
            async with Client(server.mcp) as c:
                for role, quote in sections.items():
                    result = (await c.call_tool("emsal_dogrula", {"karar_id":"bedesten:123",
                        "onerme":"Örnek tez", "alinti":quote, "pasaj_sahibi":role,
                        "gerekce":"İstemci yorumu", "degerlendirme":"destekliyor"})).data
                    self.assertTrue(result["alinti_dogrulandi"])
                    self.assertTrue(result["hukuki_degerlendirme_dogrulanmadi"])
                    self.assertFalse(result["pasaj_sahibi_dogrulandi"])
