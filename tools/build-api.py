#!/usr/bin/env python3
"""Build schema-1 compatibility APIs from schemaVersion-2 dated card sources."""
from __future__ import annotations
import copy
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RENDER_FIELDS = (
    "id", "dbfId", "name", "type", "cardClass", "rarity", "collectible",
    "cost", "text", "attack", "health", "durability", "armor", "art",
    "races", "race", "spellSchool", "set", "nativeTags", "mechanics",
    "watermark", "classes",
)
HISTORY_FIELDS = {
    "name", "type", "cardClass", "rarity", "collectible", "cost", "attack",
    "health", "durability", "armor", "text", "races", "race", "spellSchool",
}
METADATA_FIELDS = (
    "root", "relatedIds", "englishName", "expansion", "setOrder", "formats",
    "provenance", "mode",
)

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def publish(path: Path, value, compact=False):
    rendered = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        if compact else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.write_text(rendered, encoding="utf-8")
    return True

def apply_sparse_event(state: dict, event: dict, history_fields=HISTORY_FIELDS):
    """Apply assignments and explicit removals without conflating falsy values."""
    reverse = {}
    incomplete = set()
    for field, value in event.get("changes", {}).items():
        if field in history_fields:
            if field in state:
                reverse[field] = copy.deepcopy(state[field])
            else:
                incomplete.add(field)
        state[field] = copy.deepcopy(value)
    for field in event.get("remove", []):
        if field in state:
            if field in history_fields:
                reverse[field] = copy.deepcopy(state[field])
            state.pop(field)
            incomplete.add(field)
        else:
            incomplete.add(field)
    tags = {x["id"]: copy.deepcopy(x) for x in state.get("nativeTags", [])}
    for item in event.get("nativeTagUpdates", []):
        tag_id = item["id"]
        tags[tag_id] = {"id": tag_id, "value": item["value"]}
    for tag_id in event.get("nativeTagRemovals", []):
        tags.pop(tag_id, None)
    if "nativeTagUpdates" in event or "nativeTagRemovals" in event:
        state["nativeTags"] = [tags[k] for k in sorted(tags)]
        incomplete.add("nativeTags")
    return reverse, incomplete


def replay_legacy(source: dict, record: dict):
    dates = sorted(k for k in source if DATE_RE.fullmatch(k))
    if not dates or dates[0] != "2017-08-11":
        raise ValueError(f"{source.get('id')}: missing verified playable baseline")
    state = copy.deepcopy(source[dates[0]])
    revisions = []
    incomplete = set(source.get("historyIncompleteFields", []))
    previous_day = dates[0]
    for day in dates[1:]:
        event = source[day]
        if not isinstance(event, dict) or not isinstance(event.get("changes", {}), dict):
            raise ValueError(f"{source['id']}: malformed event {day}")
        reverse, blocked = apply_sparse_event(state, event)
        incomplete.update(blocked)
        if reverse:
            revisions.append({
                "from": previous_day,
                "before": day,
                "changes": reverse,
            })
        previous_day = day

    current = source["current"]
    for field in HISTORY_FIELDS:
        if field in state and field in current and state[field] != current[field]:
            raise ValueError(
                f"{source['id']}: dated replay mismatch {field}: "
                f"{state[field]!r} != {current[field]!r}"
            )
    if "nativeTags" in current and state.get("nativeTags") != current["nativeTags"]:
        incomplete.add("nativeTags")
    if "collectible" not in state and "collectible" in current:
        incomplete.add("collectible")
    if incomplete != set(source.get("historyIncompleteFields", [])):
        source["historyIncompleteFields"] = sorted(incomplete)
    return revisions

def build_indexes(write=True):
    catalog = load(ROOT / "cards.json")
    if catalog.get("schema") != 1 or not isinstance(catalog.get("cards"), list):
        raise ValueError("cards.json must remain schema 1 for legacy clients")
    records = {x["id"]: x for x in catalog["cards"]}
    if len(records) != 182:
        raise ValueError(f"Expected 182 cards.json records, found {len(records)}")
    data_paths = sorted((ROOT / "data").glob("ICC_*.json"))
    if len(data_paths) != 182 or {p.stem for p in data_paths} != set(records):
        raise ValueError("data/ card IDs do not match the complete 182-card catalogue")

    renderer = []
    history = {}
    event_count = 0
    incomplete_counts = Counter()
    for path in data_paths:
        cid = path.stem
        source = load(path)
        if source.get("schemaVersion") != 2 or source.get("id") != cid:
            raise ValueError(f"{cid}: schemaVersion 2 source required")
        record = records[cid]
        if source.get("dbfId") != record.get("dbfId") or source["current"].get("dbfId") != record.get("dbfId"):
            raise ValueError(f"{cid}: DBF ID mismatch")
        for field in METADATA_FIELDS:
            if field not in source:
                raise ValueError(f"{cid}: stable metadata field missing: {field}")
        current = source["current"]
        for field in RENDER_FIELDS:
            if field in current and field in record and current[field] != record[field]:
                raise ValueError(f"{cid}: current cache mismatch for {field}")
        revisions = replay_legacy(source, record)
        event_count += len([k for k in source if DATE_RE.fullmatch(k)]) - 1
        incomplete_counts.update(source.get("historyIncompleteFields", []))
        render_card = {field: copy.deepcopy(record[field]) for field in RENDER_FIELDS if field in record}
        if revisions:
            render_card["history"] = revisions
            history[str(record["dbfId"])] = {"id": cid, "history": revisions}
        renderer.append(render_card)
        if write and source.get("historyIncompleteFields") != load(path).get("historyIncompleteFields"):
            publish(path, source)

    render_doc = {"schema": 1, "set": catalog["set"], "cards": renderer}
    history_doc = {"schema": 1, "set": catalog["set"], "cards": history}
    changed = []
    if write:
        if publish(ROOT / "render.json", render_doc, compact=True):
            changed.append("render.json")
        if publish(ROOT / "history.json", history_doc, compact=True):
            changed.append("history.json")
    return {
        "cards": len(renderer),
        "datedCards": len(history),
        "dateEvents": event_count,
        "published": changed,
        "historyIncompleteCards": sum(1 for p in data_paths if load(p).get("historyIncompleteFields")),
        "incompleteFieldCounts": dict(sorted(incomplete_counts.items())),
    }

def main():
    print(json.dumps(build_indexes(write=True), ensure_ascii=False))

if __name__ == "__main__":
    main()
