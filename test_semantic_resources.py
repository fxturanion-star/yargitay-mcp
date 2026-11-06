"""Semantik kaynak sınırlarını gerçek ağ/model indirmesi kullanmadan doğrula."""
import asyncio
import hashlib
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp import FastMCP

import semantik


class SemanticResourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_request_rejected_before_source_calls(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        active = 0

        async def source(**kwargs):
            nonlocal active
            active += 1
            if active == 2:
                entered.set()
            await release.wait()
            return {"kararlar": [], "toplam_sonuc": 0}

        search = AsyncMock(side_effect=source)
        read = AsyncMock()
        call = semantik.register(FastMCP("capacity-test"), search, read)
        with (patch.object(semantik, "_requests", asyncio.BoundedSemaphore(2)),
              patch.object(semantik, "_slots", asyncio.BoundedSemaphore(3))):
            tasks = [asyncio.create_task(call("Somut şüphe gerekli mi?", ["şüphe"])) for _ in range(2)]
            try:
                await asyncio.wait_for(entered.wait(), 2)
                with self.assertRaisesRegex(RuntimeError, "kapasitesi dolu"):
                    await call("Somut şüphe gerekli mi?", ["şüphe"])
                self.assertEqual(search.await_count, 2)
                read.assert_not_awaited()
            finally:
                release.set()
                await asyncio.gather(*tasks, return_exceptions=True)
            self.assertEqual(semantik._requests._value, 2)

    async def test_cancelled_score_reserves_slot_until_worker_finishes(self):
        started = threading.Event()
        release = threading.Event()
        worker = ThreadPoolExecutor(max_workers=1)

        def blocked_score(question, passages):
            started.set()
            if not release.wait(2):
                raise RuntimeError("Test worker release deadline exceeded")
            return [0.5]

        with (patch.object(semantik, "_workers", worker),
              patch.object(semantik, "_slots", asyncio.BoundedSemaphore(1)),
              patch.object(semantik, "similarities", blocked_score)):
            task = asyncio.create_task(semantik._score("soru", ["pasaj"]))
            try:
                for _ in range(200):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.005)
                self.assertTrue(started.is_set())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(semantik._slots._value, 0)
                with self.assertRaisesRegex(RuntimeError, "meşgul"):
                    await semantik._score("ikinci soru", ["ikinci pasaj"])
            finally:
                release.set()
                worker.shutdown(wait=True, cancel_futures=True)
                await asyncio.sleep(0)
                await asyncio.sleep(0)
            self.assertEqual(semantik._slots._value, 1)

    def test_corrupt_model_download_preserves_old_file_and_cleans_temp(self):
        expected = hashlib.sha256(b"verified-model").hexdigest()
        response = MagicMock()
        response.iter_bytes.return_value = iter([b"corrupt-download"])
        stream = MagicMock()
        stream.__enter__.return_value = response
        with TemporaryDirectory() as directory:
            folder = Path(directory) / semantik.REVISION
            folder.mkdir()
            path = folder / "tokenizer.json"
            path.write_bytes(b"existing-invalid-file")
            with (patch.dict(os.environ, {"SEMANTIK_MODEL_CACHE": directory}),
                  patch.object(semantik, "FILES", {"tokenizer.json": expected}),
                  patch.object(semantik.httpx, "stream", return_value=stream) as download):
                with self.assertRaisesRegex(ValueError, "özeti doğrulanamadı"):
                    semantik._asset("tokenizer.json")
            self.assertEqual(path.read_bytes(), b"existing-invalid-file")
            self.assertEqual(list(folder.iterdir()), [path])
            self.assertEqual(download.call_count, 1)
            self.assertIn(semantik.REVISION, download.call_args.args[1])
