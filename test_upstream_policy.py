"""Kaynak bekleme politikası ve sayfalama sınır durumları."""
import unittest
from unittest.mock import patch

import httpx

import kaynaklar
import upstream
from metin import sayfali_belge


def _gates():
    return patch.dict(upstream.gates, {h: upstream.Gate() for h in upstream.HOSTS})


class UpstreamPolicyTest(unittest.IsolatedAsyncioTestCase):
    async def test_single_403_does_not_block_source(self):
        statuses = iter([403, 200])
        with _gates():
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda req: httpx.Response(next(statuses)))) as client:
                with self.assertRaises(httpx.HTTPStatusError):
                    await upstream.request(client, "GET", kaynaklar.HUDOC)
                response = await upstream.request(client, "GET", kaynaklar.HUDOC)
            self.assertEqual(response.status_code, 200)

    async def test_server_error_uses_short_cooldown(self):
        with _gates():
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda req: httpx.Response(500))) as client:
                with self.assertRaises(httpx.HTTPStatusError):
                    await upstream.request(client, "GET", kaynaklar.HUDOC)
            wait = (await upstream.kaynak_durumu())["HUDOC"]["bekleme_saniye"]
            self.assertTrue(0 < wait <= upstream.SERVER_ERROR_COOLDOWN)

    async def test_transport_cooldown_after_consecutive_failures(self):
        def fail(req):
            raise httpx.ConnectTimeout("timeout", request=req)
        with _gates(), patch.object(upstream.asyncio, "sleep", return_value=None):
            async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
                for _ in range(upstream.TRANSPORT_FAILURES_BEFORE_COOLDOWN - 1):
                    with self.assertRaises(httpx.ConnectTimeout):
                        await upstream.request(client, "GET", kaynaklar.HUDOC)
                    self.assertEqual((await upstream.kaynak_durumu())["HUDOC"]["bekleme_saniye"], 0)
                with self.assertRaises(httpx.ConnectTimeout):
                    await upstream.request(client, "GET", kaynaklar.HUDOC)
            self.assertGreater((await upstream.kaynak_durumu())["HUDOC"]["bekleme_saniye"], 0)


class PagingTest(unittest.TestCase):
    def test_null_limit_with_offset_returns_rest(self):
        page = sayfali_belge({"metin": "a" * 10000}, 3000, None)
        self.assertEqual(len(page["metin"]), 7000)
        self.assertIsNone(page["sonraki_baslangic"])

    def test_explicit_limit_bounds(self):
        with self.assertRaises(ValueError):
            sayfali_belge({"metin": "abc"}, 0, 20001)
        self.assertEqual(sayfali_belge({"metin": "abcdef"}, 2, 2)["metin"], "cd")


if __name__ == "__main__":
    unittest.main()
