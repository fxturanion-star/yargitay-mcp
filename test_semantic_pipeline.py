import asyncio
import os
import unittest
from unittest.mock import patch
import semantik
from test_semantik import card
import test_semantik
from unittest.mock import AsyncMock
from fastmcp import Client


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def test_candidate_fusion_beyond_old_three(self):
        a,b,target = card("1"),card("2"),card("3")
        groups = [[a,card("4"),card("5"),target],[b,card("6"),card("7"),target]]
        selected = semantik._candidate_pool(groups,18)
        self.assertEqual(selected[0]["id"], target["id"])
        self.assertEqual(len({row["id"] for row in selected}), len(selected))

    async def test_missing_home_words_is_not_an_exclusion(self):
        c = card("45")
        text = "1. Ceza Dairesi 2023/45 E., 2024/45 K. Özel yaşam alanına girilmesini haklı kılan belirtiler açıklanmamıştır."
        app = test_semantik.SemanticToolTests().app(AsyncMock(return_value={"kararlar":[c]}),AsyncMock(return_value=text))
        with patch.object(semantik.bedesten,"_kunyeler",{c["id"]:c}), patch.object(semantik,"similarities",return_value=[0.5]):
            async with Client(app) as client:
                data=(await client.call_tool("semantik_ictihat_ara",{"soru":"Konutta arama için somut şüphe gerekir mi?","arama_ifadeleri":["somut olgu"]})).data
        self.assertEqual(data["sonuclar"][0]["pasaj"],text)
        self.assertFalse(data["pasaj_sahibi_dogrulandi"])

    async def test_invalid_configuration_before_source(self):
        search = AsyncMock()
        app = test_semantik.SemanticToolTests().app(search,AsyncMock())
        with patch.dict(os.environ,{"SEMANTIK_MAX_PASSAGES":"0"}):
            async with Client(app) as client:
                r=await client.call_tool("semantik_ictihat_ara",{"soru":"Sorunun hukuki konusu"},raise_on_error=False)
                self.assertTrue(r.is_error)
        search.assert_not_awaited()
