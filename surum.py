"""Çalışan MCP kaynak dosyalarını GitHub main dalındaki değişmez ağaçla karşılaştır."""
import hashlib
import json
import subprocess
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parent
REPO = "fxturanion-star/yargitay-mcp"
FILES = ("bedesten.py", "emsal.py", "erisim.py", "hukuk_server.py", "kanun.py",
         "kaynaklar.py", "main.py", "metin.py", "passage_selection.py", "requirements.txt", "semantik.py", "server.py", "surum.py", "upstream.py")


def checkout_commit():
    try:
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=ROOT, text=True, timeout=2,
                                           stderr=subprocess.DEVNULL).strip()
        if Path(git("rev-parse", "--show-toplevel")).resolve() == ROOT:
            return git("rev-parse", "HEAD")
    except (OSError, subprocess.SubprocessError):
        pass
    for filename in ("build-revision", "release-revision"):
        marker = ROOT / filename
        if marker.is_file():
            value = marker.read_text().strip()
            if len(value) == 40 and all(c in "0123456789abcdef" for c in value):
                return value
    return None



def compare(tree):
    blobs = {item["path"]:item["sha"] for item in tree if item["type"] == "blob"}
    differences = []
    for name in FILES:
        path = ROOT / name
        if not path.is_file():
            differences.append(name)
            continue
        data = path.read_bytes()
        oid = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blobs.get(name) != oid:
            differences.append(name)
    return differences


def catalog_report(tools):
    """İstemci ve sunucu araç şemalarını aynı kanonik JSON biçimine dönüştür."""
    schemas = []
    for tool in tools:
        schemas.append({"name":tool.name,
                        "input":getattr(tool, "inputSchema", getattr(tool, "parameters", None)),
                        "output":getattr(tool, "outputSchema", getattr(tool, "output_schema", None))})
    schemas.sort(key=lambda item:item["name"])
    def digest(data):
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()
    critical = {"semantik_ictihat_ara", "yargitay_toplu_arastirma", "yargitay_karar_ara",
                "yargitay_baglanti_testi"}
    return {"arac_sayisi":len(schemas), "araclar":[s["name"] for s in schemas],
            "sema_sha256":digest(schemas),
            "kritik_sema_sha256":{s["name"]:digest(s) for s in schemas if s["name"] in critical}}


async def kontrol(tools=None):
    local = checkout_commit()
    catalog = catalog_report(tools) if tools is not None else None
    base = f"https://api.github.com/repos/{REPO}"
    try:
        async with httpx.AsyncClient(timeout=12, headers={"User-Agent":"yargitay-mcp-release"}) as client:
            response = await client.get(base + "/commits/main")
            response.raise_for_status()
            commit = response.json()
            revision = commit["sha"]
            # GitHub'ın tree uç noktası kök dizindeki tüm dağıtım dosyalarını tek yanıtta verir.
            response = await client.get(base + "/git/trees/" + commit["commit"]["tree"]["sha"])
            response.raise_for_status()
            tree = response.json()
            if tree.get("truncated"):
                raise ValueError("Eksik GitHub ağacı")
            differences = compare(tree["tree"])
    except (OSError, httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        return {"durum":"doğrulanamadı", "neden":type(exc).__name__, "calisan_commit":local, "arac_katalogu":catalog}
    return {"durum":"eşleşiyor" if not differences and local in (None, revision) else "farklı",
            "github_main":revision, "calisan_commit":local, "commit_kimligi_dogrulandi":local == revision and not differences,
            "calisma_dosyalari_eslesiyor":not differences, "denetlenen_dosya":len(FILES),
            "farkli_dosyalar":differences, "arac_katalogu":catalog}
