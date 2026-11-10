#!/usr/bin/env python3
"""Verify original CardDefs Tag transitions and synchronize existing ICC dated events."""
from __future__ import annotations
import copy
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources" / "frozen-throne-native-tag-evidence.json"
OFFICIAL_PATCH_SOURCES = {
    "2017-09-19": "https://hearthstone.blizzard.com/ko-kr/news/21037556",
    "2018-02-07": "https://hearthstone.blizzard.com/ko-kr/news/21507224",
    "2021-03-26": "https://hearthstone.blizzard.com/ko-kr/news/23642550",
    "2022-11-30": "https://hearthstone.blizzard.com/ko-kr/news/23882860/25-0-patch-notes",
    "2024-10-30": "https://hearthstone.blizzard.com/ko-kr/news/24149389/31-0-patch-notes",
}

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def local_name(tag):
    return tag.rsplit("}", 1)[-1]

def parse_snapshot(path: Path, wanted: set[str]):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {}
    for _, entity in ET.iterparse(path, events=("end",)):
        if local_name(entity.tag) != "Entity":
            continue
        cid = entity.attrib.get("CardID")
        if cid not in wanted:
            entity.clear()
            continue
        tags = {}
        for child in list(entity):
            if local_name(child.tag) != "Tag":
                continue
            attrs = child.attrib
            if "enumID" not in attrs or "value" not in attrs:
                continue
            tag_id = int(attrs["enumID"])
            raw_value = attrs["value"]
            try:
                value = int(raw_value)
            except ValueError:
                value = raw_value
            tags[tag_id] = value
        result[cid] = {"dbfId": int(entity.attrib["ID"]), "tags": tags}
        entity.clear()
    missing = wanted - set(result)
    if missing:
        raise RuntimeError(f"{path.name}: missing CardIDs {sorted(missing)}")
    return digest, result

def state_matches(actual, expected):
    if not isinstance(expected, dict) or "present" not in expected:
        return False
    if not expected["present"]:
        return actual is None
    return actual is not None and actual == expected.get("value")

def merge_operations(event, tag_id, after):
    updates = {x["id"]: copy.deepcopy(x) for x in event.get("nativeTagUpdates", [])}
    removals = set(event.get("nativeTagRemovals", []))
    if after["present"]:
        value = after["value"]
        if tag_id in updates and updates[tag_id]["value"] != value:
            raise RuntimeError(f"conflicting Tag {tag_id} update: {updates[tag_id]['value']} != {value}")
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
    groups = manifest.get("groups", [])
    if manifest.get("schemaVersion") != 1 or len(groups) != 5:
        raise RuntimeError("Expected five B-stage original Tag evidence groups")
    wanted_by_commit = {}
    for group in groups:
        for side in ("before", "after"):
            wanted_by_commit.setdefault(group[side]["commit"], set()).update(
                card["id"] for card in group["cards"]
            )

    snapshots = {}
    for group in groups:
        for side in ("before", "after"):
            meta = group[side]
            commit = meta["commit"]
            if commit in snapshots:
                continue
            path = snapshot_dir / f"CardDefs-{commit}.xml"
            if not path.exists():
                raise RuntimeError(f"Missing immutable CardDefs snapshot: {path}")
            digest, cards = parse_snapshot(path, wanted_by_commit[commit])
            if digest != meta["xmlSha256"]:
                raise RuntimeError(f"{commit}: SHA-256 mismatch {digest} != {meta['xmlSha256']}")
            snapshots[commit] = cards

    # Verify every supplied before/after value against the immutable XML before editing anything.
    for group in groups:
        before_cards = snapshots[group["before"]["commit"]]
        after_cards = snapshots[group["after"]["commit"]]
        for card in group["cards"]:
            cid = card["id"]
            if before_cards[cid]["dbfId"] != after_cards[cid]["dbfId"]:
                raise RuntimeError(f"{cid}:{group['day']}: DBF ID changed across snapshots")
            for tag_text, observation in card.get("nativeTags", {}).items():
                tag_id = int(tag_text)
                before_value = before_cards[cid]["tags"].get(tag_id)
                after_value = after_cards[cid]["tags"].get(tag_id)
                if not state_matches(before_value, observation["before"]):
                    raise RuntimeError(
                        f"{cid}:{group['day']}: Tag {tag_id} before mismatch "
                        f"{before_value!r} != {observation['before']!r}"
                    )
                if not state_matches(after_value, observation["after"]):
                    raise RuntimeError(
                        f"{cid}:{group['day']}: Tag {tag_id} after mismatch "
                        f"{after_value!r} != {observation['after']!r}"
                    )

    updated_cards = 0
    changed_tags = 0
    unchanged_observations = 0
    already_synchronized = 0
    new_operations = 0
    for group in groups:
        day = group["day"]
        official = OFFICIAL_PATCH_SOURCES.get(day)
        for card in group["cards"]:
            cid = card["id"]
            path = ROOT / "data" / f"{cid}.json"
            source = load(path)
            if source.get("schemaVersion") != 2:
                raise RuntimeError(f"{cid}: expected schemaVersion 2")
            if day not in source or not isinstance(source[day], dict):
                raise RuntimeError(f"{cid}:{day}: existing dated event is missing")
            event = source[day]
            if not isinstance(event.get("changes", {}), dict):
                raise RuntimeError(f"{cid}:{day}: malformed canonical changes")
            if source.get("patchSources", {}).get(day) is None:
                raise RuntimeError(f"{cid}:{day}: existing patchSources provenance is missing")
            for field, expected in card.get("changes", {}).items():
                actual = event.get("changes", {}).get(field)
                if actual != expected:
                    raise RuntimeError(f"{cid}:{day}: canonical {field} mismatch {actual!r} != {expected!r}")

            current_before = copy.deepcopy(source["current"])
            launch_before = copy.deepcopy(source["2017-08-11"])
            patch_sources_before = copy.deepcopy(source.get("patchSources", {}))
            existing_updates = {x["id"]: x["value"] for x in event.get("nativeTagUpdates", [])}
            existing_removals = set(event.get("nativeTagRemovals", []))
            applied = []
            unchanged = []
            for tag_text, observation in sorted(card.get("nativeTags", {}).items(), key=lambda x: int(x[0])):
                tag_id = int(tag_text)
                before = observation["before"]
                after = observation["after"]
                if before == after:
                    unchanged.append(tag_id)
                    unchanged_observations += 1
                    continue
                changed_tags += 1
                if after["present"]:
                    expected_value = after["value"]
                    if existing_updates.get(tag_id) == expected_value and tag_id not in existing_removals:
                        already_synchronized += 1
                    else:
                        new_operations += 1
                    merge_operations(event, tag_id, after)
                    applied.append({"id": tag_id, "operation": "update", "value": expected_value})
                else:
                    if tag_id in existing_removals and tag_id not in existing_updates:
                        already_synchronized += 1
                    else:
                        new_operations += 1
                    merge_operations(event, tag_id, after)
                    applied.append({"id": tag_id, "operation": "remove"})

            patch_source = source["patchSources"][day]
            official_source = patch_source if isinstance(patch_source, str) and patch_source.startswith("http") else official
            evidence_sources = [x for x in (official_source, group["before"]["source"], group["after"]["source"]) if x]
            existing_sources = event.get("sources", [])
            if isinstance(existing_sources, str):
                existing_sources = [existing_sources]
            event["sources"] = list(dict.fromkeys(list(existing_sources) + evidence_sources))
            evidence = {
                "groupId": f"B-{day}",
                "classification": "verified_original_native_tag_transition",
                "day": day,
                "patchSource": patch_source,
                "officialPatchSource": official_source,
                "archiveBefore": copy.deepcopy(group["before"]),
                "archiveAfter": copy.deepcopy(group["after"]),
                "observedNativeTags": copy.deepcopy(card.get("nativeTags", {})),
                "changedTagOperations": applied,
                "unchangedTagIds": unchanged,
                "sourceURLs": evidence_sources,
            }
            records = {x["groupId"]: x for x in event.get("nativeTagEvidence", [])}
            records[evidence["groupId"]] = evidence
            event["nativeTagEvidence"] = [records[k] for k in sorted(records)]
            if source["current"] != current_before:
                raise RuntimeError(f"{cid}: current cache changed during B-stage synchronization")
            if source["2017-08-11"] != launch_before:
                raise RuntimeError(f"{cid}: launch baseline changed during B-stage synchronization")
            if source.get("patchSources", {}) != patch_sources_before:
                raise RuntimeError(f"{cid}: patchSources were modified")
            save(path, source)
            updated_cards += 1

    print(json.dumps({
        "verifiedSnapshots": len(snapshots),
        "groups": len(groups),
        "existingEvents": sum(len(g["cards"]) for g in groups),
        "updatedCards": updated_cards,
        "changedTagObservations": changed_tags,
        "unchangedTagObservations": unchanged_observations,
        "alreadySynchronizedOperations": already_synchronized,
        "newTagOperations": new_operations,
        "newDateRows": 0,
        "currentNativeTagsChanged": 0,
        "launchBaselinesChanged": 0,
    }, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply-icc-native-tags.py /tmp")
    main(Path(sys.argv[1]))
