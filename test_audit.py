import unittest
from unittest.mock import AsyncMock, patch

import bedesten
import kanun
import kaynaklar
import server


class AuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_page_boundary(self):
        async def source(path, data, paging):
            self.assertTrue(paging)
            self.assertEqual(data["pageSize"], 20)
            start = (data["pageNumber"] - 1) * 20
            return {"total": 52, "records": list(range(start, min(start + 20, 52)))}
        with patch.object(bedesten, "request", source):
            result = await bedesten.search_page("/", {"pageSize": 25, "pageNumber": 2}, "records")
            self.assertEqual(result["records"], list(range(25, 50)))
            result = await bedesten.search_page("/", {"pageSize": 25, "pageNumber": 3}, "records")
            self.assertEqual(result["records"], [50, 51])

    async def test_reject_wrong_law(self):
        rows = [{"mevzuatId": "17", "mevzuatNo": 5271, "mevzuatTur": {"id": 1},
                 "mevzuatTertip": 3, "mevzuatAdi": "Başka kanun"}]
        with patch.object(kanun, "_search", AsyncMock(return_value=(rows, 1))):
            with self.assertRaises(LookupError):
                await kanun._resolve("1.5.5271")

    def test_exact_article(self):
        base = {"maddeId": "10", "maddeNo": 1, "mevzuatId": "20", "children": []}
        labels = ["Ek Madde No: 1", "Geçici Madde No: 1", "Madde No: 1/A", "Madde No: 1 - Başlık"]
        tree = {"children": [{**base, "maddeBaslik": label} for label in labels]}
        self.assertEqual(list(kanun._article_ids(tree, "20", 1)), ["10"])

    async def test_dates_and_offsets(self):
        with self.assertRaises(ValueError):
            await server._do_search(baslangic_tarihi="31.02.2025")
        with self.assertRaises(ValueError):
            await server._do_search(baslangic_tarihi="01.03.2025", bitis_tarihi="01.02.2025")
        with self.assertRaises(ValueError):
            await kaynaklar.aihm_ara(ilk_tarih="2025-01-01", son_tarih="2024-01-01")
        with self.assertRaises(ValueError):
            kaynaklar.page("belge", 5)

    async def test_cooldown_and_invalid_content(self):
        with patch.object(bedesten, "_blocked_until", bedesten.time.monotonic() + 60):
            with self.assertRaisesRegex(RuntimeError, "istek sınırı"):
                await bedesten.request("/test", {})
        with patch.object(bedesten, "request", AsyncMock(return_value={"content": "%%"})):
            with self.assertRaisesRegex(ValueError, "kodlaması"):
                await bedesten.document("123")

    def test_disabled_cache(self):
        with patch.object(server, "_CACHE_MAX", 0), patch.object(server, "_doc_cache", {}):
            server._cache_put("test", "belge")
            self.assertEqual(server._doc_cache, {})


if __name__ == "__main__":
    unittest.main()
