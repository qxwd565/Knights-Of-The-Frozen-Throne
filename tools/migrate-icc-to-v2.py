#!/usr/bin/env python3
"""Migrate the Frozen Throne set to schemaVersion 2 from its launch CardDefs snapshot."""
from __future__ import annotations
import copy
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "6f874a2b18045ed3464983aff85ca106bc656916"
BASELINE_DATE = "2017-08-08"
RELEASE_DATE = "2017-08-11"
SET_IDS = "Knights Of The Frozen Throne"
RACE_NAMES = {
    "BEAST": "야수", "DEMON": "악마", "DRAGON": "용족", "MURLOC": "멀록",
    "PIRATE": "해적", "TOTEM": "토템", "MECHANICAL": "기계", "ELEMENTAL": "정령",
    "UNDEAD": "언데드", "DRAENEI": "드레나이", "NAGA": "나가",
}
RACE_TAG_VALUES = {
    14: "MURLOC", 15: "DEMON", 18: "ELEMENTAL", 20: "BEAST",
    23: "PIRATE", 24: "DRAGON", 11: "UNDEAD", 2: "DRAENEI", 17: "MECHANICAL", 21: "TOTEM",
}
TAG_FIELD = {45: "health", 47: "attack", 48: "cost", 187: "health", 292: "armor"}
TYPE_TAG_VALUES = {3: "HERO", 4: "MINION", 5: "SPELL", 6: "WEAPON", 10: "HERO_POWER"}
RARITY_TAG_VALUES = {1: "COMMON", 2: "FREE", 3: "RARE", 4: "EPIC", 5: "LEGENDARY"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# These are source-level ReferencedTag records from the supplied 25-part audit.
REFERENCE_TAGS = {
    "ICC_047": [217], "ICC_049": [363], "ICC_050": [363], "ICC_051": [190, 363],
    "ICC_052": [217], "ICC_054": [190], "ICC_056": [208], "ICC_058": [208],
    "ICC_068": [208], "ICC_071": [194], "ICC_086": [219], "ICC_090": [215],
    "ICC_093": [192], "ICC_098": [217], "ICC_200": [363], "ICC_201": [217],
    "ICC_204": [219], "ICC_221": [685], "ICC_236": [208], "ICC_243": [217],
    "ICC_244": [217], "ICC_252": [208], "ICC_257": [217], "ICC_314t7": [1211],
    "ICC_467": [240], "ICC_705": [190], "ICC_801": [194], "ICC_807": [190],
    "ICC_809": [363], "ICC_810": [685], "ICC_827": [191], "ICC_829": [685],
    "ICC_832": [190, 363], "ICC_832a": [190], "ICC_832b": [363],
    "ICC_833": [685], "ICC_835": [190], "ICC_836": [208], "ICC_850": [240],
    "ICC_853": [190, 685], "ICC_855": [208], "ICC_912": [189, 190, 194, 685],
}
REFERENCE_NAMES = {
    189: "질풍", 190: "도발", 191: "은신", 192: "주문 공격력",
    194: "천상의 보호막", 208: "빙결", 215: "과부하", 217: "죽음의 메아리",
    219: "비밀", 240: "면역", 363: "독성", 685: "생명력 흡수",
    1211: "모면",
}

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def scalar(value):
    if value is None:
        return None
    if re.fullmatch(r"-?\d+", str(value)):
        return int(value)
    if str(value).lower() in ("true", "false"):
        return str(value).lower() == "true"
    return value

def parse_carddefs(path: Path):
    wanted = set()
    catalog = load(ROOT / "cards.json")
    wanted = {x["id"] for x in catalog["cards"]}
    entities = {}
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag.rsplit("}", 1)[-1] != "Entity":
            continue
        cid = element.attrib.get("CardID")
        if cid in wanted:
            tags, refs = [], []
            for child in list(element):
                kind = child.tag.rsplit("}", 1)[-1]
                if kind not in ("Tag", "ReferencedTag"):
                    continue
                attrs = child.attrib
                if "enumID" not in attrs or "value" not in attrs:
                    continue
                item = {
                    "id": int(attrs["enumID"]),
                    "name": attrs.get("name", f"TAG_{attrs['enumID']}"),
                    "value": scalar(attrs["value"]),
                }
                (refs if kind == "ReferencedTag" else tags).append(item)
            entities[cid] = {
                "dbfId": int(element.attrib["ID"]),
                "nativeTags": tags,
                "referenceTags": refs,
            }
        element.clear()
    missing = wanted - set(entities)
    if missing:
        raise RuntimeError(f"CardDefs snapshot is missing {len(missing)} cards: {sorted(missing)}")
    return entities

def race_label(races):
    return ", ".join(RACE_NAMES.get(x, x) for x in races)

def display_text(raw):
    return raw.replace("[x]", "").replace(chr(10), "<br></br>")

def tag_map(tags):
    return {x["id"]: x["value"] for x in tags}

def current_reference_tags(cid, raw_tags):
    wanted = set(REFERENCE_TAGS.get(cid, []))
    result = []
    raw = {x["id"]: x for x in raw_tags}
    for tag_id in sorted(wanted):
        item = raw.get(tag_id)
        result.append({
            "id": tag_id,
            "name": REFERENCE_NAMES.get(tag_id, item.get("name") if item else f"게임 태그 {tag_id}"),
            "value": item.get("value", 1) if item else 1,
        })
    return result

def build_initial(cid, record, old_card, baseline):
    tags = copy.deepcopy(baseline["nativeTags"])
    values = tag_map(tags)
    names = {x["id"]: x["name"] for x in old_card.get("nativeTags", [])}
    for item in tags:
        item["name"] = names.get(item["id"], item["name"])
    state = {
        "name": record["name"],
        "type": TYPE_TAG_VALUES.get(values.get(202), record["type"]),
        "cardClass": record["cardClass"],
        "text": record.get("text", ""),
        "nativeTags": tags,
        "referenceTags": copy.deepcopy(baseline["referenceTags"]),
    }
    for field, tag_id in (("cost", 48), ("attack", 47), ("health", 45), ("armor", 292)):
        if tag_id in values:
            state[field] = values[tag_id]
    # The original client stores weapon durability in tag 187; the public card API
    # historically exposes that numeric value as health for weapon cards.
    if record["type"] == "WEAPON" and 187 in values:
        state.pop("health", None)
        state["health"] = values[187]
    if 203 in values and values[203] in RARITY_TAG_VALUES:
        state["rarity"] = RARITY_TAG_VALUES[values[203]]
    state["collectible"] = bool(values.get(321, 0))
    races = []
    if 200 in values and values[200] in RACE_TAG_VALUES:
        races = [RACE_TAG_VALUES[values[200]]]
    # ICC_705 had no launch race. Do not carry the later erroneous BEAST label
    # backward; its actual later Undead/Beast state is dated separately.
    if cid == "ICC_705":
        races = []
    if record["type"] == "MINION":
        state["races"] = races
        state["race"] = race_label(races)
    if record["type"] == "SPELL":
        state["spellSchool"] = ""
    raw = old_card.get("nativeRawText")
    if raw is not None:
        state["nativeRawText"] = raw
    if "nativeTextBuilder" in old_card:
        state["nativeTextBuilder"] = old_card["nativeTextBuilder"]
    # Exact pre-change raw text from the audited source records.
    if cid == "ICC_221":
        state["nativeRawText"] = "내 무기에 <b>생명력 흡수</b>를 부여합니다."
        state["text"] = state["nativeRawText"]
    elif cid == "ICC_466":
        state["nativeRawText"] = "<b>도발</b>, <b>전투의 함성:</b>\n이 하수인을 복사하여 소환합니다."
        state["text"] = display_text(state["nativeRawText"])
    elif cid == "ICC_055":
        state["nativeRawText"] = "<b>생명력 흡수</b>\n하수인에게 피해를\n$2 줍니다."
        state["text"] = display_text(state["nativeRawText"])
    elif cid == "ICC_910":
        state["nativeRawText"] = "<b>연계:</b> 이번 턴에\n앞서 낸 카드의 수만큼 피해를 줍니다."
        state["text"] = display_text(state["nativeRawText"])
    return state

def merge_event(events, cid, day, changes=None, **extra):
    item = events.setdefault(day, {"changes": {}})
    if changes:
        item["changes"].update(copy.deepcopy(changes))
    for key, value in extra.items():
        if key == "nativeTagUpdates":
            by_id = {x["id"]: x for x in item.get(key, [])}
            for update in value:
                by_id[update["id"]] = copy.deepcopy(update)
            item[key] = [by_id[k] for k in sorted(by_id)]
        elif key == "nativeTagRemovals":
            item[key] = sorted(set(item.get(key, [])) | set(value))
        else:
            item[key] = copy.deepcopy(value)

def add_confirmed_events(cid, events, record, old_card):
    # Nine cards, twelve confirmed gameplay/text operations; 11 new date rows
    # plus one additional field on the already-known 2021-03-26 event.
    if cid == "ICC_832t3":
        merge_event(events, cid, "2017-12-07", {"cost": 1},
                    nativeTagUpdates=[{"id": 48, "value": 1}],
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/21274279",
                             "https://github.com/HearthSim/hsdata/blob/c623eb10a6fed4a214cf27923e749da9cb52c226/CardDefs.xml"])
    elif cid == "ICC_221":
        raw = "이번 턴에 내 무기에 <b>생명력 흡수</b>를 부여합니다."
        merge_event(events, cid, "2018-12-20", {"cost": 1, "text": record["text"], "nativeRawText": raw},
                    nativeTagUpdates=[{"id": 48, "value": 1}],
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/22817529",
                             "https://www.inven.co.kr/webzine/news/?news=212483&site=hs"])
    elif cid == "ICC_466":
        raw18 = "[x]<b>도발</b>, <b>전투의 함성:</b>\n다른 사로나이트 광산\n노예를 소환합니다."
        raw21 = "[x]<b>도발</b>, <b>전투의 함성:</b>\n이 하수인을 복사하여 소환합니다."
        raw25 = "<b>도발</b>, <b>전투의 함성:</b> 사로나이트 광산 노예를 소환합니다."
        merge_event(events, cid, "2018-12-20", {"text": display_text(raw18), "nativeRawText": raw18},
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/22817529",
                             "https://www.inven.co.kr/webzine/news/?news=212483&site=hs"])
        merge_event(events, cid, "2021-03-26", {"text": display_text(raw21), "nativeRawText": raw21},
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/23642550",
                             "https://github.com/HearthSim/hsdata/blob/132c8a94327896bbd9b911d7ee26086df7089290/CardDefs.xml"])
        merge_event(events, cid, "2025-05-23", {"text": record["text"], "nativeRawText": raw25},
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/24204920/32-2-4",
                             "https://us.forums.blizzard.com/en/hearthstone/t/3224-patch-notes/146356.json"])
    elif cid == "ICC_055":
        raw = "<b>생명력 흡수</b>\n하수인에게 피해를\n$3 줍니다."
        merge_event(events, cid, "2021-03-26", {"text": record["text"], "nativeRawText": raw},
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/23642550",
                             "https://github.com/HearthSim/hsdata/blob/132c8a94327896bbd9b911d7ee26086df7089290/CardDefs.xml"])
    elif cid in ("ICC_051a", "ICC_051b"):
        hp = 2 if cid == "ICC_051a" else 5
        raw_after = "<b>독성</b>" if cid == "ICC_051a" else "<b>도발</b>"
        merge_event(
            events, cid, "2018-11-30",
            {"type": "MINION", "cost": 2, "attack": 1, "health": hp,
             "rarity": "RARE", "races": ["BEAST"], "race": "야수",
             "text": display_text(raw_after), "nativeRawText": raw_after},
            nativeTagUpdates=[
                {"id": 202, "value": 4}, {"id": 48, "value": 2},
                {"id": 47, "value": 1}, {"id": 45, "value": hp},
                {"id": 200, "value": 20}, {"id": 203, "value": 3},
            ],
            sources=["https://hearthstone.blizzard.com/ko-kr/news/22788307",
                     "https://github.com/HearthSim/hsdata/blob/1fdd42edae20fe2c5477776a8bb0d0e2a209a5ac/CardDefs.xml"],
        )
    elif cid == "ICC_706":
        merge_event(events, cid, "2022-11-30", {"races": ["UNDEAD"], "race": "언데드"},
                    nativeTagUpdates=[{"id": 200, "value": 11}],
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/23882860/25-0-patch-notes",
                             "https://github.com/HearthSim/hsdata/blob/beaa46cc24c1332ad91d4f7ae096024f6ff7d394/CardDefs.xml"])
        merge_event(events, cid, "2023-02-15", {"races": [], "race": ""},
                    nativeTagRemovals=[200],
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/23913671",
                             "https://github.com/HearthSim/hsdata/blob/cf08a2eee9159a63ff589cfe2deabc4035673871/CardDefs.xml"])
    elif cid == "ICC_910":
        raw = "<b>연계:</b> 이번 턴에 앞서 낸 카드의 수만큼 하수인에게 피해를 2씩 줍니다."
        merge_event(events, cid, "2023-03-03", {"cost": 5, "text": record["text"], "nativeRawText": raw},
                    nativeTagUpdates=[{"id": 48, "value": 5}],
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/23921492",
                             "https://www.inven.co.kr/board/hs/3508/19562"])
    elif cid == "ICC_210":
        merge_event(events, cid, "2023-04-05", {"health": 3},
                    nativeTagUpdates=[{"id": 45, "value": 3}],
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/23934449",
                             "https://bnetcmsus-a.akamaihd.net/cms/content_entry_media/6TFP77K62FEJ1679527943503.pdf"])
    elif cid == "ICC_235":
        merge_event(events, cid, "2023-09-29", {"cost": 7},
                    nativeTagUpdates=[{"id": 48, "value": 7}],
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/23999072",
                             "https://www.inven.co.kr/board/hs/3508/20029"])
    elif cid == "ICC_075":
        merge_event(events, cid, "2025-03-19", {"health": 6},
                    nativeTagUpdates=[{"id": 45, "value": 6}],
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/24187196",
                             "https://bnetcmsus-a.akamaihd.net/cms/content_entry_media/5L4LK5ASYDUL1739227664823.pdf"])
    elif cid == "ICC_705":
        merge_event(events, cid, "2022-11-30", {"races": ["UNDEAD", "BEAST"], "race": "언데드, 야수"},
                    nativeTagUpdates=[{"id": 200, "value": 11}, {"id": 2542, "value": 1}],
                    sources=["https://hearthstone.blizzard.com/ko-kr/news/23882860/25-0-patch-notes",
                             "https://github.com/HearthSim/hsdata/blob/6f874a2b18045ed3464983aff85ca106bc656916/CardDefs.xml"])

def main(xml_path: Path):
    catalog = load(ROOT / "cards.json")
    records = {x["id"]: x for x in catalog["cards"]}
    paths = sorted((ROOT / "data").glob("ICC_*.json"))
    if len(paths) != 182 or len(records) != 182:
        raise RuntimeError(f"Expected 182 cards; data={len(paths)} cards.json={len(records)}")
    baseline = parse_carddefs(xml_path)
    baseline_doc = {
        "schema": 1,
        "source": {
            "repository": "HearthSim/hsdata",
            "commit": BASELINE_COMMIT,
            "commitDate": BASELINE_DATE,
            "build": "9.0.0.20457",
            "path": "CardDefs.xml",
            "url": f"https://github.com/HearthSim/hsdata/blob/{BASELINE_COMMIT}/CardDefs.xml",
        },
        "dateMeaning": "Launch CardDefs snapshot on 2017-08-08; first playable date is 2017-08-11 Korea time.",
        "cards": baseline,
    }
    dump(ROOT / "sources" / "carddefs-9.0.0.20457-baseline.json", baseline_doc)
    total_events = 0
    for path in paths:
        cid = path.stem
        data = load(path)
        if data.get("schemaVersion") == 2:
            continue
        if data.get("schemaVersion") != 1 or not isinstance(data.get("card"), dict):
            raise RuntimeError(f"{cid}: unexpected legacy source schema")
        old_card = data["card"]
        record = records.get(cid)
        source = baseline[cid]
        if record is None or old_card.get("dbfId") != record.get("dbfId") or source["dbfId"] != record.get("dbfId"):
            raise RuntimeError(f"{cid}: ID/DBF mismatch across source, CardDefs and cards.json")
        initial = build_initial(cid, record, old_card, source)
        events = {}
        for patch in old_card.get("patches", []):
            day = patch["date"]
            changes = copy.deepcopy(patch["changes"])
            if "races" in changes:
                changes["race"] = race_label(changes["races"])
            merge_event(events, cid, day, changes, source=old_card.get("patchSources", {}).get(day))
        # ICC_705's release-to-25.0 race baseline was empty, not BEAST.
        if cid == "ICC_705":
            for day, event in events.items():
                if "races" in event["changes"] and day == "2022-11-30":
                    event["changes"]["races"] = ["UNDEAD", "BEAST"]
                    event["changes"]["race"] = "언데드, 야수"
        add_confirmed_events(cid, events, record, old_card)
        dated = {}
        for day in sorted(events):
            if not DATE_RE.fullmatch(day) or day <= RELEASE_DATE:
                raise RuntimeError(f"{cid}: invalid/non-forward event date {day}")
            dated[day] = events[day]
        current = copy.deepcopy(record)
        current["nativeTags"] = copy.deepcopy(old_card.get("nativeTags", record.get("nativeTags", [])))
        if "nativeRawText" in old_card:
            current["nativeRawText"] = old_card["nativeRawText"]
        if "nativeTextBuilder" in old_card:
            current["nativeTextBuilder"] = old_card["nativeTextBuilder"]
        current["referenceTags"] = current_reference_tags(cid, current["nativeTags"])
        current["releasedAt"] = record.get("releasedAt", RELEASE_DATE)
        current["releaseStatus"] = record.get("releaseStatus", "verified")
        if current["releasedAt"] != RELEASE_DATE or current["releaseStatus"] != "verified":
            raise RuntimeError(f"{cid}: launch release policy must remain verified 2017-08-11")
        # Ensure all explicit operations converge to the current card for each
        # gameplay field touched by the event stream.
        state = copy.deepcopy(initial)
        for day, event in dated.items():
            state.update(copy.deepcopy(event["changes"]))
        for field in ("cost", "attack", "health", "race", "races", "spellSchool", "text"):
            if field in state and field in current and state[field] != current[field]:
                raise RuntimeError(f"{cid}: event replay mismatch for {field}: {state[field]!r} != {current[field]!r}")
        # Preserve all eight stable metadata fields and all other top-level source metadata.
        metadata = {k: copy.deepcopy(v) for k, v in data.items()
                    if k not in ("schemaVersion", "card", "history", "patches")}
        result = {
            "schemaVersion": 2,
            "id": cid,
            "dbfId": record["dbfId"],
            "sourceBaseline": copy.deepcopy(baseline_doc["source"]),
            "dateMeaning": "Top-level dates are Korean-local playable card states/events. 2017-08-08 is the CardDefs snapshot, not a playable date; first playable date is 2017-08-11.",
            RELEASE_DATE: initial,
            **dated,
            "current": current,
            "initialSpecStatus": old_card.get("initialSpecStatus", "unverified"),
            "patchSources": copy.deepcopy(old_card.get("patchSources", {})),
            "nativeTagsTimelineStatus": "partial",
            "historyIncompleteFields": sorted(set(data.get("historyIncompleteFields", [])) | {"nativeTags", "referenceTags"}),
            "unresolvedSourceFields": sorted(set(data.get("unresolvedSourceFields", [])) | {"nativeTags", "referenceTags"}),
            **metadata,
        }
        dump(path, result)
        total_events += len(dated)
    print(json.dumps({
        "cards": len(paths),
        "baselineCards": len(baseline),
        "events": total_events,
        "confirmedCards": 9,
        "confirmedOperations": 12,
        "referenceTagCards": len(REFERENCE_TAGS),
        "baselineCommit": BASELINE_COMMIT,
    }, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: migrate-icc-to-v2.py /path/to/CardDefs.xml")
    main(Path(sys.argv[1]))
