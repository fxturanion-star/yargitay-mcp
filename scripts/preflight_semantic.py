"""MCP/model preflight on three pinned official decision records.

Usage: python scripts/preflight_semantic.py --source /path/source.json
Source is a list of {id, metin, kaynak}. Record acquisition is a separate live
operation. This test uses in-process MCP with an offline source replay, runs the
real pinned embedding model, and is not a claim that Cloud is deployed.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastmcp import Client
import bedesten
import semantik
import server


CASES = (
    {"id":"bedesten:1163161600", "kind":"CGK", "daire":"Ceza Genel Kurulu",
     "esas_no":"2024/360", "karar_no":"2025/151", "karar_tarihi":"09.04.2025",
     "sha256":"7ebdf2926397e8f9ecac39cfcc90785921a0f91bc0b2fcde18846145aeb7b9b5",
     "soru":"Konutta aramada iki işlem tanığının hazır bulunmamasının delile etkisi nedir?"},
    {"id":"bedesten:498482500", "kind":"uzun karar", "daire":"Ceza Genel Kurulu",
     "esas_no":"2016/75", "karar_no":"2019/18", "karar_tarihi":"17.01.2019",
     "sha256":"41faed6febf39f61009f4c3f40ba2c16aaee034a15f68732da73e904a513be1b",
     "soru":"Arama yapılabilmesi için soyut şüphe yeterli midir, somut olgular gerekir mi?"},
    {"id":"bedesten:1018167800", "kind":"ceza dairesi", "daire":"1. Ceza Dairesi",
     "esas_no":"2022/8669", "karar_no":"2024/1416", "karar_tarihi":"04.03.2024",
     "sha256":"f7a6ee4a3c294ee408079e2046a5996b0a498f40ac3e0cf131a831465d0c61a1",
     "soru":"Ceza yargılamasında bozma sonrası yapılan uygulamanın hukuki denetimi nasıl yapılır?"},
)


def require_cached_model():
    folder = Path(os.getenv("SEMANTIK_MODEL_CACHE", Path.home()/".cache"/"yargitay-mcp")) / semantik.REVISION
    for name, digest in semantik.FILES.items():
        path = folder / Path(name).name
        if not path.is_file():
            raise RuntimeError("Preflight requires a separately prepared pinned model cache.")
        with path.open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != digest:
                raise ValueError("Cached model digest mismatch: " + path.name)


def validated_sources(path):
    records = json.loads(Path(path).read_text())
    by_id = {row["id"]:row for row in records}
    if len(by_id) != len(records):
        raise ValueError("Duplicate source record id.")
    for case in CASES:
        row = by_id[case["id"]]
        digest = hashlib.sha256(row["metin"].encode("utf-8")).hexdigest()
        if digest != case["sha256"]:
            raise ValueError("Pinned source digest mismatch: " + case["id"])
        expected_url = f"{bedesten.SITE}/ictihat/{case['id'].removeprefix('bedesten:')}"
        if row["kaynak"] != expected_url:
            raise ValueError("Official source URL mismatch.")
        # Each pinned text concludes with the independently recorded decision date.
        if case["karar_tarihi"] not in row["metin"][-1800:]:
            raise ValueError("Reference date missing from decision conclusion.")
    return by_id


def verify_result(report, card, text):
    assert report["durum"] == "deneysel"
    assert report["hukuki_uygunluk_dogrulandi"] is False
    assert report["pasaj_sahibi_dogrulandi"] is False
    assert report["incelenen_aday"] == 1 and len(report["sonuclar"]) == 1
    result = report["sonuclar"][0]
    for key in ("id", "daire", "esas_no", "karar_no", "karar_tarihi", "kaynak"):
        assert result[key] == card[key], key
    assert "E./K. doğrulandı" in result["kunye_durumu"]
    start, end = result["baslangic"], result["bitis"]
    assert 0 <= start < end <= len(text)
    assert result["pasaj"] == text[start:end]
    assert 1 <= len(result["pasaj"]) <= 680
    assert math.isfinite(result["benzerlik"]) and -1.00001 <= result["benzerlik"] <= 1.00001
    return result


async def preflight(path):
    records = validated_sources(path)
    require_cached_model()
    reports = []
    # Do not allow silent external downloads or legal-source lookups in replay.
    forbidden = AssertionError("Preflight replay attempted external network access.")
    with (patch("httpx.AsyncClient", side_effect=forbidden),
          patch("httpx.stream", side_effect=forbidden)):
        async with Client(server.mcp) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert len(names) == 22
            assert {"semantik_ictihat_ara", "yargitay_toplu_arastirma", "yargitay_karar_metni"} <= names
            for index, case in enumerate(CASES):
                row = records[case["id"]]
                text = row["metin"]
                card = {key:case[key] for key in ("id","daire","esas_no","karar_no","karar_tarihi")}
                card["kaynak"] = row["kaynak"]
                # This source boundary returns the already acquired official record.
                source = AsyncMock(return_value={"toplam_sonuc":1,"sayfa":1,"sayfa_boyutu":1,
                                                "kararlar":[card],"kaynak":"official-record replay"})
                with (patch.object(bedesten, "judgments", source),
                      patch.object(bedesten, "_kunyeler", {card["id"]:card}),
                      patch.object(server, "_doc_cache", {card["id"]:text})):
                    started = time.perf_counter()
                    direct = (await client.call_tool("semantik_ictihat_ara", {
                        "soru":case["soru"], "arama_ifadeleri":["arama"], "daire":case["daire"],
                        "aday_sayisi":1,"sonuc_sayisi":1})).data
                    direct_seconds = time.perf_counter()-started
                    selected = verify_result(direct, card, text)
                    # Same inputs: the compatibility route generates its own query terms.
                    # A single source record remains the identical candidate pool.
                    started = time.perf_counter()
                    compatibility = (await client.call_tool("yargitay_toplu_arastirma", {
                        "aranan_kelime":case["soru"], "daire":case["daire"],
                        "metin_bicimi":"semantik","metin_sayisi":1,"sonuc_sayisi":1})).data
                    compatibility_seconds = time.perf_counter()-started
                    other = verify_result(compatibility, card, text)
                    assert selected == other
                    for mode in ("pencere", "tam"):
                        old = (await client.call_tool("yargitay_toplu_arastirma", {
                            "aranan_kelime":"arama", "daire":case["daire"],
                            "metin_bicimi":mode,"metin_sayisi":1,"sonuc_sayisi":1})).data
                        assert old["metin_bicimi"] == mode and old["kararlar"] == [card]
                        assert len(old["metinler"]) == 1 and old["metinler"][0]["id"] == card["id"]
                        if mode == "tam":
                            assert old["metinler"][0]["metin"] == text
                    page = (await client.call_tool("yargitay_karar_metni", {
                        "karar_id":card["id"],"baslangic":selected["baslangic"],
                        "karakter_sayisi":selected["bitis"]-selected["baslangic"]})).data
                    assert page["metin"] == selected["pasaj"] and page["kaynak"] == card["kaynak"]
                reports.append({"kind":case["kind"],"id":card["id"], "kunye":card,
                                "source_chars":len(text),"source_sha256":case["sha256"],
                                "selected_start":selected["baslangic"],"selected_end":selected["bitis"],
                                "direct_seconds":round(direct_seconds,4),
                                "compatibility_seconds":round(compatibility_seconds,4),
                                "model_first_call_includes_load":index == 0,
                                "mocked_source_boundary_calls":source.await_count,
                                "direct_compatibility_same_selected_passage":True,
                                "source_offset_and_card_verified":True,"legacy_modes_passed":True})
    return {"mode":"offline official-record replay via in-process MCP", "tools":len(names),
            "model":semantik.MODEL,"revision":semantik.REVISION,
            "source_network_requests_during_replay":0,
            "legal_relevance_or_majority_attribution_verified":False,
            "cloud_deployment_verified":False,
            "process_peak_rss_mib":round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,3),
            "cases":reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(preflight(args.source)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
