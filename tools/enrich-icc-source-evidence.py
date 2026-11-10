#!/usr/bin/env python3
"""Attach source citations and recover card-level migration notes from the legacy source."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_NAMES = {
    189: "질풍", 190: "도발", 191: "은신", 192: "주문 공격력",
    194: "천상의 보호막", 208: "빙결", 215: "과부하", 217: "죽음의 메아리",
    219: "비밀", 240: "면역", 363: "독성", 685: "생명력 흡수", 1211: "모면",
}
SOURCES = {
    ("ICC_832t3", "2017-12-07"): [
        "https://hearthstone.blizzard.com/ko-kr/news/21274279",
        "https://github.com/HearthSim/hsdata/blob/c623eb10a6fed4a214cf27923e749da9cb52c226/CardDefs.xml",
    ],
    ("ICC_221", "2018-12-20"): [
        "https://hearthstone.blizzard.com/ko-kr/news/22817529",
        "https://www.inven.co.kr/webzine/news/?news=212483&site=hs",
    ],
    ("ICC_466", "2018-12-20"): [
        "https://hearthstone.blizzard.com/ko-kr/news/22817529",
        "https://www.inven.co.kr/webzine/news/?news=212483&site=hs",
    ],
    ("ICC_466", "2021-03-26"): [
        "https://hearthstone.blizzard.com/ko-kr/news/23642550",
        "https://github.com/HearthSim/hsdata/blob/132c8a94327896bbd9b911d7ee26086df7089290/CardDefs.xml",
    ],
    ("ICC_466", "2025-05-23"): [
        "https://hearthstone.blizzard.com/ko-kr/news/24204920/32-2-4",
        "https://us.forums.blizzard.com/en/hearthstone/t/3224-patch-notes/146356.json",
    ],
    ("ICC_055", "2021-03-26"): [
        "https://hearthstone.blizzard.com/ko-kr/news/23642550",
        "https://github.com/HearthSim/hsdata/blob/132c8a94327896bbd9b911d7ee26086df7089290/CardDefs.xml",
    ],
    ("ICC_051a", "2018-11-30"): [
        "https://hearthstone.blizzard.com/ko-kr/news/22788307",
        "https://github.com/HearthSim/hsdata/blob/1fdd42edae20fe2c5477776a8bb0d0e2a209a5ac/CardDefs.xml",
    ],
    ("ICC_051b", "2018-11-30"): [
        "https://hearthstone.blizzard.com/ko-kr/news/22788307",
        "https://github.com/HearthSim/hsdata/blob/1fdd42edae20fe2c5477776a8bb0d0e2a209a5ac/CardDefs.xml",
    ],
    ("ICC_706", "2022-11-30"): [
        "https://hearthstone.blizzard.com/ko-kr/news/23882860/25-0-patch-notes",
        "https://github.com/HearthSim/hsdata/blob/beaa46cc24c1332ad91d4f7ae096024f6ff7d394/CardDefs.xml",
    ],
    ("ICC_706", "2023-02-15"): [
        "https://hearthstone.blizzard.com/ko-kr/news/23913671",
        "https://github.com/HearthSim/hsdata/blob/cf08a2eee9159a63ff589cfe2deabc4035673871/CardDefs.xml",
    ],
    ("ICC_910", "2023-03-03"): [
        "https://hearthstone.blizzard.com/ko-kr/news/23921492",
        "https://www.inven.co.kr/board/hs/3508/19562",
    ],
    ("ICC_210", "2023-04-05"): [
        "https://hearthstone.blizzard.com/ko-kr/news/23934449",
        "https://bnetcmsus-a.akamaihd.net/cms/content_entry_media/6TFP77K62FEJ1679527943503.pdf",
    ],
    ("ICC_235", "2023-09-29"): [
        "https://hearthstone.blizzard.com/ko-kr/news/23999072",
        "https://www.inven.co.kr/board/hs/3508/20029",
    ],
    ("ICC_075", "2025-03-19"): [
        "https://hearthstone.blizzard.com/ko-kr/news/24187196",
        "https://bnetcmsus-a.akamaihd.net/cms/content_entry_media/5L4LK5ASYDUL1739227664823.pdf",
    ],
    ("ICC_705", "2022-11-30"): [
        "https://hearthstone.blizzard.com/ko-kr/news/23882860/25-0-patch-notes",
        "https://github.com/HearthSim/hsdata/blob/6f874a2b18045ed3464983aff85ca106bc656916/CardDefs.xml",
    ],
}

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def git_json(commit, path):
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)

def annotate_reference_tags(items):
    for item in items:
        item["sourceType"] = "ReferencedTag"
        item["label"] = REFERENCE_NAMES.get(item["id"], item.get("name", ""))
    return items

def main(commit):
    paths = sorted((ROOT / "data").glob("ICC_*.json"))
    if len(paths) != 182:
        raise RuntimeError(f"Expected 182 card sources, found {len(paths)}")
    updated = 0
    for path in paths:
        cid = path.stem
        source = load(path)
        legacy = git_json(commit, f"data/{cid}.json")
        old_card = legacy.get("card", {})
        source["initialSpecStatus"] = old_card.get("initialSpecStatus", "unverified")
        source["patchSources"] = old_card.get("patchSources", {})
        for key in [k for k in source if len(k) == 10 and k[4] == "-" and k[7] == "-"]:
            if (cid, key) in SOURCES:
                source[key]["sources"] = SOURCES[(cid, key)]
        for day in [k for k in source if len(k) == 10 and k[4] == "-" and k[7] == "-"]:
            if "referenceTags" in source[day]:
                annotate_reference_tags(source[day]["referenceTags"])
        if "referenceTags" in source.get("current", {}):
            annotate_reference_tags(source["current"]["referenceTags"])
        path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated += 1

    manifest_path = ROOT / "sources" / "carddefs-9.0.0.20457-baseline.json"
    manifest = load(manifest_path)
    for item in manifest["cards"].values():
        annotate_reference_tags(item["referenceTags"])
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cards": updated, "eventsWithSources": len(SOURCES), "legacyCommit": commit}, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: enrich-icc-source-evidence.py <legacy-commit>")
    main(sys.argv[1])
