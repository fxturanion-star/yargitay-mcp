import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx
import kaynaklar
import surum


class ReleaseTests(unittest.IsolatedAsyncioTestCase):
    def test_git_blob_includes_filename_and_content(self):
        tree = [{"type":"blob","path":"example","sha":"ce013625030ba8dba906f756967f9e9ca394464a"}]
        with TemporaryDirectory() as tmp, patch.object(surum, "ROOT", Path(tmp)), patch.object(surum, "FILES", ("example",)):
            self.assertEqual(surum.compare(tree), ["example"])
            (Path(tmp) / "example").write_bytes(b"hello\n")
            self.assertEqual(surum.compare(tree), [])
            (Path(tmp) / "example").write_bytes(b"changed")
            self.assertEqual(surum.compare(tree), ["example"])

    def test_runtime_manifest_covers_project_modules(self):
        modules = {p.name for p in surum.ROOT.glob("*.py") if not p.name.startswith("test_")}
        self.assertEqual(modules | {"requirements.txt"}, set(surum.FILES))

    async def test_official_archive_after_missing_index(self):
        first = httpx.Response(200, text="<html></html>")
        second = httpx.Response(200, text='<a href="20261106-1.htm">Yönetmelik</a>')
        fetch = AsyncMock(side_effect=[first, second])
        with patch.object(kaynaklar, "fetch", fetch):
            result = await kaynaklar.resmi_gazete_fihrist("2026-11-06")
        self.assertTrue(result["resmi_kaynak"])
        self.assertTrue(result["kaynak"].endswith("/eskiler/2026/11/20261106.htm"))

    async def test_timeout_does_not_trigger_second_request(self):
        fetch = AsyncMock(side_effect=httpx.ReadTimeout("Yanıt bekleme süresi doldu."))
        with patch.object(kaynaklar, "fetch", fetch), self.assertRaisesRegex(RuntimeError, "ReadTimeout"):
            await kaynaklar.resmi_gazete_fihrist("2026-11-06")
        self.assertEqual(fetch.await_count, 1)
