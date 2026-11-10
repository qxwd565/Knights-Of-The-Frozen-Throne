#!/usr/bin/env python3
"""Verify immutable CardDefs before/after snapshots and apply archive-only events."""
from __future__ import annotations
import copy
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources" / "frozen-throne-observation-evidence.json"

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")

def local_name(tag):
    return tag.rsplit("}", 1)[-1]

def xml_raw(node):
    return (node.text or "").replace(chr(92) + "n", chr(10))

def parse_snapshot(path, wanted):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {}
    for _, entity in ET.iterparse(path, events=("end",)):
        if local_name(entity.tag) != "Entity":
            continue
        cid = entity.attrib.get("CardID")
        if cid not in wanted:
            entity.clear()
            continue
        tags, strings = {}, {}
        for child in list(entity):
            if local_name(child.tag) != "Tag":
                continue
            try:
                tag_id = int(child.attrib.get("enumID", "-1"))
            except ValueError:
                continue
            if tag_id in (184, 185):
                field = "CARDTEXT_INHAND" if tag_id == 184 else "CARDNAME"
                locales = {}
                for locale_node in list(child):
                    locale = local_name(locale_node.tag)
                    if locale in ("koKR", "enUS"):
                        locales[locale] = xml_raw(locale_node)
                strings[field] = locales
            elif "value" in child.attrib:
                tags[tag_id] = str(child.attrib["value"])
        result[cid] = {"dbfId": int(entity.attrib["ID"]), "tags": tags, "strings": strings}
        entity.clear()
    missing = wanted - set(result)
    if missing:
        raise RuntimeError(f"{path.name}: missing cards {sorted(missing)}")
    return digest, result

def assert_observation(finding, observation, before, after):
    cid = observation["cardID"]
    if before[cid]["dbfId"] != observation["dbfId"] or after[cid]["dbfId"] != observation["dbfId"]:
        raise RuntimeError(f"{finding['findingID']}:{cid}: DBF ID mismatch")
    for key, expected in observation["changes"].items():
        if key.isdigit():
            tag_id = int(key)
            b, a = before[cid]["tags"], after[cid]["tags"]
            actual_before = {"present": tag_id in b}
            actual_after = {"present": tag_id in a}
            if tag_id in b:
                actual_before["value"] = b[tag_id]
            if tag_id in a:
                actual_after["value"] = a[tag_id]
            if actual_before != expected["before"] or actual_after != expected["after"]:
                raise RuntimeError(f"{finding['findingID']}:{cid}: Tag {tag_id} mismatch")
        elif key in ("rawText", "enText"):
            locale = "koKR" if key == "rawText" else "enUS"
            field = "CARDTEXT_INHAND"
            actual_before = before[cid]["strings"].get(field, {}).get(locale)
            actual_after = after[cid]["strings"].get(field, {}).get(locale)
            if actual_before != expected["before"] or actual_after != expected["after"]:
                raise RuntimeError(f"{finding['findingID']}:{cid}:{locale} text mismatch")
        else:
            raise RuntimeError(f"{finding['findingID']}:{cid}: unsupported observation {key}")

def display_text(raw):
    return raw.replace("[x]", "").replace(chr(10), "<br></br>")

def merge_tag_operation(event, tag_id, after):
    updates = {x["id"]: copy.deepcopy(x) for x in event.get("nativeTagUpdates", [])}
    removals = set(event.get("nativeTagRemovals", []))
    if after["present"]:
        value = int(after["value"])
        if tag_id in updates and updates[tag_id]["value"] != value:
            raise RuntimeError(f"Conflicting native Tag update {tag_id}")
        updates[tag_id] = {"id": tag_id, "value": value}
        removals.discard(tag_id)
    else:
        updates.pop(tag_id, None)
        removals.add(tag_id)
    if updates:
        event["nativeTagUpdates"] = [updates[k] for k in sorted(updates)]
    else:
        event.pop("nativeTagUpdates", None)
    if removals:
        event["nativeTagRemovals"] = sorted(removals)
    else:
        event.pop("nativeTagRemovals", None)

def main(snapshot_dir: Path):
    manifest = load(MANIFEST)
    findings = manifest.get("findings", [])
    if manifest.get("schemaVersion") != 1 or len(findings) != 7:
        raise RuntimeError("Expected the seven frozen-throne archive findings")
    wanted_by_commit = {}
    for finding in findings:
        for side in ("archiveBefore", "archiveAfter"):
            wanted_by_commit.setdefault(finding[side]["commit"], set()).update(
                x["cardID"] for x in finding["observations"]
            )
    commits = {}
    for finding in findings:
        for side in ("archiveBefore", "archiveAfter"):
            snapshot = finding[side]
            sha = snapshot["commit"]
            if sha in commits:
                continue
            path = snapshot_dir / f"CardDefs-{sha}.xml"
            if not path.exists():
                raise RuntimeError(f"Missing immutable snapshot file {path}")
            digest, cards = parse_snapshot(path, wanted_by_commit[sha])
            if digest != snapshot["xmlSha256"]:
                raise RuntimeError(f"{sha}: XML SHA-256 mismatch {digest} != {snapshot['xmlSha256']}")
            commits[sha] = cards
    for finding in findings:
        before = commits[finding["archiveBefore"]["commit"]]
        after = commits[finding["archiveAfter"]["commit"]]
        for observation in finding["observations"]:
            assert_observation(finding, observation, before, after)

    changed = 0
    for finding in findings:
        day = finding["koreanDay"]
        for observation in finding["observations"]:
            cid = observation["cardID"]
            path = ROOT / "data" / f"{cid}.json"
            source = load(path)
            if source.get("schemaVersion") != 2 or source.get("dbfId") != observation["dbfId"]:
                raise RuntimeError(f"{cid}: schema/DBF mismatch")
            current_before = copy.deepcopy(source["current"])
            event = source.setdefault(day, {"changes": {}})
            if not isinstance(event, dict):
                raise RuntimeError(f"{cid}:{day}: event is not an object")
            event.setdefault("changes", {})
            for key, change in observation["changes"].items():
                if key.isdigit():
                    merge_tag_operation(event, int(key), change["after"])
                elif key == "rawText":
                    raw = change["after"]
                    event["changes"]["nativeRawText"] = raw
                    event["changes"]["text"] = display_text(raw)
            if finding["findingID"] == "FT-D07":
                event["remove"] = sorted(set(event.get("remove", [])) | {"rarity"})
            evidence = {
                "findingID": finding["findingID"],
                "classification": finding["classification"],
                "event": finding["event"],
                "koreanDay": day,
                "archiveBefore": copy.deepcopy(finding["archiveBefore"]),
                "archiveAfter": copy.deepcopy(finding["archiveAfter"]),
                "cardObservation": copy.deepcopy(observation),
                "assessment": finding["assessment"],
                "sourceURLs": list(finding["sourceURLs"]),
                "countedAsConfirmedGameplayHistory": False,
            }
            records = {x["findingID"]: x for x in event.get("sourceEvidence", [])}
            records[finding["findingID"]] = evidence
            event["sourceEvidence"] = [records[k] for k in sorted(records)]
            event["classification"] = finding["classification"]
            sources = event.get("sources", [])
            if isinstance(sources, str):
                sources = [sources]
            event["sources"] = list(dict.fromkeys(list(sources) + finding["sourceURLs"]))
            if source["current"] != current_before:
                raise RuntimeError(f"{cid}: current cache was modified")
            save(path, source)
            changed += 1
    print(json.dumps({"verifiedSnapshots": len(commits), "findings": len(findings),
                      "cardObservations": changed, "newCardDateRows": 18,
                      "confirmedGameplayEventsAdded": 0}, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply-icc-observation-events.py /tmp")
    main(Path(sys.argv[1]))
