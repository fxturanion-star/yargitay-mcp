"""Yetkili Gateway bağlantısından, bu push'un çalışan sürüme ulaştığını kontrol et."""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import surum
from server import mcp

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


async def main():
    token = os.getenv("FASTMCP_VERIFY_TOKEN")
    if not token:
        sys.exit("FASTMCP_VERIFY_TOKEN tanımlı değil; bulut sürümü doğrulanamadı.")
    expected = os.environ["GITHUB_SHA"]
    expected_catalog = surum.catalog_report(await mcp.list_tools())
    transport = StreamableHttpTransport("https://bah-yargitay.fastmcp.app/mcp", auth=token)
    deadline = time.monotonic() + 420
    while time.monotonic() < deadline:
        try:
            async with asyncio.timeout(45), Client(transport) as client:
                result = await client.call_tool("yargitay_baglanti_testi", {"surum_kontrolu":True})
                report = result.data
                actual_catalog = surum.catalog_report(await client.list_tools())
            print(report, flush=True)
            schema_matches = actual_catalog == expected_catalog
            print({"istemci_katalogu_eslesiyor":schema_matches,
                   "beklenen_sema_sha256":expected_catalog["sema_sha256"],
                   "calisan_sema_sha256":actual_catalog["sema_sha256"]}, flush=True)
            if (report["durum"] == "eşleşiyor" and report["github_main"] == expected
                    and report["commit_kimligi_dogrulandi"] and report["calisma_dosyalari_eslesiyor"]
                    and schema_matches and report.get("arac_katalogu") == actual_catalog):
                return
        except Exception as exc:
            # Taşıyıcı istisnalarında URL ve yetki başlıklarını günlüğe yazma.
            print("Sürüm sorgusu tamamlanamadı:", type(exc).__name__, flush=True)
        await asyncio.sleep(20)
    sys.exit("Süre doldu: çalışan commit ve dosya eşleşmesi doğrulanamadı.")


if __name__ == "__main__":
    asyncio.run(main())
