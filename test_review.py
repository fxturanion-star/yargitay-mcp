import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastmcp import Client, FastMCP
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from starlette.testclient import TestClient

import bedesten
import erisim
import kaynaklar
import server
import upstream


class ReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_attribution_is_not_certified(self):
        text = "A" * 4100 + " KARŞIOY: Bu gerekçeye katılmıyorum."
        with patch.object(server, "_fetch_doc_text", AsyncMock(return_value=text)):
            async with Client(server.mcp) as c:
                result = await c.call_tool("emsal_dogrula", {
                    "onerme": "Mahkemenin görüşü", "karar_id": "bedesten:12",
                    "alinti": "Bu gerekçeye katılmıyorum.", "degerlendirme": "destekliyor",
                    "pasaj_sahibi": "mahkemenin gerekçesi", "gerekce": "İstemci iddiası"})
                self.assertTrue(result.data["alinti_dogrulandi"])
                self.assertTrue(result.data["hukuki_degerlendirme_dogrulanmadi"])
                self.assertFalse(result.data["pasaj_sahibi_dogrulandi"])
                page = (await c.call_tool("yargitay_karar_metni", {"karar_id":"bedesten:12"})).data
                self.assertEqual(page["sonraki_baslangic"], 4000)

    async def test_source_cooldown_is_independent(self):
        calls = []
        def reply(req):
            calls.append(req.url.host)
            return httpx.Response(429 if req.url.host == "hudoc.echr.coe.int" else 200,
                                  headers={"Retry-After":"100"})
        with patch.dict(upstream.gates, {h: upstream.Gate() for h in upstream.HOSTS}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as c:
                with self.assertRaises(httpx.HTTPStatusError):
                    await upstream.request(c, "GET", kaynaklar.HUDOC)
                with self.assertRaises(httpx.RequestError):
                    await upstream.request(c, "GET", kaynaklar.HUDOC)
                await upstream.request(c, "GET", kaynaklar.YOK)
            self.assertEqual(len(calls), 2)
            self.assertGreater((await upstream.kaynak_durumu())["HUDOC"]["bekleme_saniye"], 0)

    async def test_official_only_uses_no_secondary(self):
        fetch = AsyncMock(side_effect=httpx.ConnectError("offline"))
        with patch.object(kaynaklar, "fetch", fetch), self.assertRaisesRegex(RuntimeError, "fihrist"):
            await kaynaklar.resmi_gazete_fihrist("2026-11-06")
        self.assertEqual(fetch.await_count, 1)

    async def test_concurrent_identical_search_calls_source_once(self):
        result = {"toplam_sonuc": 0, "kararlar": []}
        async def fetch(query):
            await asyncio.sleep(0)
            return result
        query = {"aranan": "concurrent test", "pageSize": 1, "pageNumber": 1}
        with patch.object(bedesten, "_search_judgments", AsyncMock(side_effect=fetch)) as source:
            one, two = await asyncio.gather(bedesten.judgments(query), bedesten.judgments(query))
        self.assertEqual(one, two)
        self.assertEqual(source.await_count, 1)

    async def test_schema(self):
        async with Client(server.mcp) as client:
            schema = {t.name:t.inputSchema for t in await client.list_tools()}
            self.assertEqual(len(schema), 22)
            self.assertIn("soru", schema["semantik_ictihat_ara"]["required"])
            self.assertIs(schema["resmi_gazete_fihrist"]["properties"]["ikincil_kaynak"]["default"], False)
            self.assertEqual(schema["yargitay_karar_metni"]["properties"]["karakter_sayisi"]["default"], 4000)

    def test_partial_auth_and_public_bind_fail_closed(self):
        with patch.dict(os.environ, {"MCP_HOST":"0.0.0.0", "MCP_JWT_ISSUER":"test"}, clear=True):
            with self.assertRaises(ValueError):
                erisim.token_verifier()
            with self.assertRaises(ValueError):
                erisim.http_host(False)

    def test_http_rejects_unauthenticated_and_wrong_audience(self):
        keys = RSAKeyPair.generate()
        issuer = "https://issuer.example"
        with patch.dict(os.environ, {"MCP_JWT_PUBLIC_KEY":keys.public_key,
                                     "MCP_JWT_ISSUER":issuer, "MCP_JWT_AUDIENCE":"mcp"}, clear=True):
            app = FastMCP("test", auth=erisim.token_verifier()).http_app()
        body = {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
            "protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}
        with TestClient(app) as client:
            for aud, expected in [(None,401), ("wrong",401), ("mcp",200)]:
                headers = {"Accept":"application/json, text/event-stream"}
                if aud:
                    headers["Authorization"] = "Bearer " + keys.create_token(issuer=issuer, audience=aud)
                response = client.post("/mcp", headers=headers, json=body)
                self.assertEqual(response.status_code, expected)
