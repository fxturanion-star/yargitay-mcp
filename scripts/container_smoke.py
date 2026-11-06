"""Gerçek imaj içinde SHA, kaynak dosyası ve MCP kataloğunu ağsız doğrula."""
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,"/app")

from fastmcp import Client
import server
import surum


async def main():
    expected = os.environ['EXPECTED_SHA']
    if surum.checkout_commit() != expected:
        raise AssertionError('İmajın commit damgası beklenen SHA ile eşleşmiyor.')
    manifest = json.loads(Path('/expected/files.json').read_text())
    for name, digest in manifest.items():
        actual = hashlib.sha256((Path('/app')/name).read_bytes()).hexdigest()
        if digest != actual:
            raise AssertionError('İmajda kaynak dosyası uyuşmuyor: '+name)
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert len(names) == 22
        assert {'semantik_ictihat_ara','yargitay_toplu_arastirma','yargitay_karar_metni'} <= names
        assert surum.catalog_report(tools) == surum.catalog_report(await server.mcp.list_tools())
        result = await client.call_tool('yargitay_daire_listesi',{})
        assert 'Ceza Genel Kurulu' in result.data['daireler']
    print(json.dumps({'commit':expected,'runtime_files':len(manifest),'tools':len(names),'network':'disabled'}))


if __name__ == '__main__':
    asyncio.run(main())
