#!/usr/bin/env python3
"""Apply immutable launch CardDefs localized strings to schema-v2 ICC sources."""
from __future__ import annotations
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
RELEASE_DATE = "2017-08-11"
SOURCE = "sources/carddefs-9.0.0.20457-baseline.json"
BASELINE_URL = "https://github.com/HearthSim/hsdata/blob/6f874a2b18045ed3464983aff85ca106bc656916/CardDefs.xml"

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def display_text(raw):
    return raw.replace("[x]", "").replace("\n", "<br></br>")

def main():
    fixture = load(ROOT / SOURCE)
    if fixture.get("source", {}).get("commit") != "6f874a2b18045ed3464983aff85ca106bc656916":
        raise SystemExit("Unexpected launch strings fixture source")
    cards = fixture["cards"]
    paths = sorted((ROOT / "data").glob("ICC_*.json"))
    if len(paths) != 182 or set(cards) != {p.stem for p in paths}:
        raise SystemExit("Launch fixture and 182 schema2 data files do not match")
    for path in paths:
        cid = path.stem
        data = load(path)
        if data.get("schemaVersion") != 2:
            raise SystemExit(f"{cid}: schemaVersion 2 required")
        launch = data.get(RELEASE_DATE)
        if not isinstance(launch, dict):
            raise SystemExit(f"{cid}: release initialState missing")
        strings = cards[cid].get("localizedStrings", {})
        name = strings.get("CARDNAME", {})
        text = strings.get("CARDTEXT_INHAND", {})
        ko_name = name.get("locales", {}).get("koKR", {})
        ko_text = text.get("locales", {}).get("koKR", {})
        if name.get("tagPresent") is True and ko_name.get("present") is True:
            launch["name"] = ko_name["nativeRawText"]
        if text.get("tagPresent") is not True or ko_text.get("present") is not True:
            launch.pop("text", None)
            launch.pop("nativeRawText", None)
            launch.pop("nativeTextBuilder", None)
        else:
            raw = ko_text["nativeRawText"]
            launch["nativeRawText"] = raw
            launch["text"] = "" if cid == "ICC_828t" else display_text(raw)
            launch.pop("nativeTextBuilder", None)
        kind = launch.get("type")
        if kind == "SPELL":
            for field in ("attack", "health", "durability", "armor", "races", "race", "spellSchool"):
                launch.pop(field, None)
        elif kind == "MINION":
            for field in ("armor", "durability", "spellSchool"):
                launch.pop(field, None)
        elif kind == "HERO":
            launch.pop("health", None)
        elif kind == "WEAPON":
            durability = next((x["value"] for x in launch.get("nativeTags", []) if x.get("id") == 187), None)
            launch.pop("health", None)
            if durability is not None:
                launch["durability"] = durability
        save(path, data)
    for path in paths:
        data = load(path)
        initial, current = data[RELEASE_DATE], data["current"]
        observations = {}
        for field in ("name", "text", "nativeRawText", "nativeTextBuilder"):
            ip, cp = field in initial, field in current
            if ip != cp or (ip and initial[field] != current[field]):
                observations[field] = {
                    "launch": {"present": ip, **({"value": initial[field]} if ip else {})},
                    "current": {"present": cp, **({"value": current[field]} if cp else {})},
                    "transitionDate": None, "source": BASELINE_URL,
                    "note": "Launch/current observations differ; transition date is not established."
                }
        if observations:
            data["timelineIncompleteFields"] = observations
        else:
            data.pop("timelineIncompleteFields", None)
        save(path, data)
    print(json.dumps({"cards": len(paths), "source": SOURCE}, ensure_ascii=False))

if __name__ == "__main__":
    main()
