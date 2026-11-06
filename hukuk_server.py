from fastmcp import FastMCP
from server import mcp as yargitay_mcp
from turk_hukuku_mevzuat import server as mevzuat

mcp = FastMCP("Yargıtay ve Mevzuat")

mcp.mount(yargitay_mcp)

mcp.tool(
    mevzuat.madde_getir,
    name="mevzuat_madde_getir",
)
mcp.tool(
    mevzuat.kanun_metni_getir,
    name="mevzuat_kanun_metni_getir",
)
mcp.tool(
    mevzuat.mevzuat_ara,
    name="mevzuat_ara",
)
mcp.tool(
    mevzuat.bilinen_kanunlar,
    name="mevzuat_bilinen_kanunlar",
)
