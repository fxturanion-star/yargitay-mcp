"""Kaynak yönlendirmesi ve kelimesiz sorgu için ağsız MCP testi."""
import asyncio
import base64
from unittest.mock import patch
from fastmcp import Client
import server


async def main():
    paths = []
    async def reply(path, data, paging=False):
        paths.append(path)
        if path.endswith("searchDocuments"):
            assert "phrase" not in data
            assert data["birimAdi"] == "Ceza Genel Kurulu"
            assert data["kararTarihiStart"] == "2026-09-01T00:00:00"
            return {"total":1,"emsalKararList":[{"documentId":"123","birimAdi":"Ceza Genel Kurulu",
                    "esasNo":"2026/1","kararNo":"2026/2","kararTarihiStr":"03.09.2026"}]}
        assert path.endswith("getDocumentContent") and data == {"documentId":"123"}
        return {"mimeType":"text/html","content":base64.b64encode(b"<p>belge</p>").decode()}
    with patch.object(server.bedesten,"request",reply):
        async with Client(server.mcp) as c:
            r=await c.call_tool("yargitay_karar_ara",{"daire":"Ceza Genel Kurulu","baslangic_tarihi":"01.09.2026"})
            k=r.data["kararlar"][0]["id"]
            assert k=="bedesten:123"
            d=await c.call_tool("yargitay_karar_metni",{"karar_id":k})
            assert d.data["metin"]=="belge"
            assert paths==["/emsal-karar/searchDocuments","/emsal-karar/getDocumentContent"]
    print("Arama ve metin testi geçti.")


if __name__=="__main__":
    asyncio.run(main())
