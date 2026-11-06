import unittest
from unittest.mock import AsyncMock, patch

from fastmcp import Client

import kanun
import server


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_lossless_mcp_pages_and_legacy_calls(self):
        text = "Şüphe…\n🧑‍⚖️ " * 50
        law = {"metin": text, "uzunluk": len(text), "kaynak": "resmi-kaynak", "mevzuat_id": "1.5.5271"}
        with (patch.object(kanun.primary, "kanun_metni_getir", AsyncMock(return_value=law)),
              patch.object(server, "_fetch_doc_text", AsyncMock(return_value=text))):
            async with Client(server.mcp) as client:
                for tool, params in [("yargitay_karar_metni", {"karar_id": "bedesten:123"}),
                                     ("mevzuat_kanun_metni_getir", {"kanun": "CMK"})]:
                    full = {**params, "karakter_sayisi": None} if tool == "yargitay_karar_metni" else params
                    original = (await client.call_tool(tool, full)).data
                    self.assertEqual(original["metin"], text)
                    self.assertNotIn("sonraki_baslangic", original)
                    parts, start = [], 0
                    versions = set()
                    while start is not None:
                        page = (await client.call_tool(tool, {**params, "baslangic": start,
                                                              "karakter_sayisi": 83})).data
                        self.assertEqual(page["kaynak"], original["kaynak"])
                        self.assertEqual(page["toplam_karakter"], len(text))
                        versions.add(page["metin_surumu"])
                        parts.append(page["metin"])
                        start = page["sonraki_baslangic"]
                    self.assertEqual("".join(parts), text)
                    self.assertEqual(len(versions), 1)
                    for bad in [{"karakter_sayisi": 0}, {"karakter_sayisi": 20001},
                                {"baslangic": len(text)}, {"baslangic": -1}]:
                        reply = await client.call_tool(tool, {**params, **bad}, raise_on_error=False)
                        self.assertTrue(reply.is_error)

    def test_dense_excerpt_is_bounded(self):
        text = "makul şüphe " * 5000
        excerpt = server._keyword_windows(text, "makul şüphe")
        self.assertLessEqual(len(excerpt), 5601)
        self.assertTrue(excerpt.endswith("…"))
        self.assertEqual(excerpt[:-1], text[:5600])
        self.assertEqual(server._keyword_windows("Kararda makul şüphe geçiyor.", "şüphe"),
                         "Kararda makul şüphe geçiyor.")
