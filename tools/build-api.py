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
HISTORY_FIELDS = (
    "name", "type", "cardClass", "rarity", "collectible", "cost", "attack",
    "health", "durability", "armor", "text", "races", "race", "spellSchool",
)
HISTORY_FIELD_SET = frozenset(HISTORY_FIELDS)
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

def apply_sparse_event(state: dict, event: dict, history_fields=HISTORY_FIELD_SET):
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


def applicable_history_fields(state: dict):
    """Return fields meaningful for this card type, not legacy zero-value aliases."""
    fields = set(HISTORY_FIELDS)
    kind = state.get("type")
    if kind == "SPELL":
        fields.difference_update({"attack", "health", "durability", "armor", "races", "race"})
    else:
        if kind != "HERO":
            fields.discard("armor")
        if kind != "WEAPON":
            fields.discard("durability")
        if kind != "SPELL":
            fields.discard("spellSchool")
        if kind != "MINION":
            fields.difference_update({"races", "race"})
        if kind in ("HERO", "WEAPON"):
            fields.discard("health")
    return tuple(field for field in HISTORY_FIELDS if field in fields)


def snapshot_field(state: dict, field: str):
    return {"present": field in state, **({"value": copy.deepcopy(state[field])} if field in state else {})}


def replay_legacy(source: dict, record: dict):
    """Replay canonical states and derive complete legacy intervals and explicit limits."""
    dates = sorted(k for k in source if DATE_RE.fullmatch(k))
    if not dates or dates[0] != "2017-08-11":
        raise ValueError(f"{source.get('id')}: missing verified playable baseline")
    initial = copy.deepcopy(source[dates[0]])
    state = copy.deepcopy(initial)
    snapshots = [(dates[0], copy.deepcopy(state))]
    field_dates = {}
    reasons = {}
    compatibility = {}

    def reason(field, code, detail):
        reasons.setdefault(field, []).append({"code": code, "detail": detail})

    initial_tags = {x["id"]: x for x in initial.get("nativeTags", [])}
    def empty_text_projection(field):
        return (
            field in ("text", "nativeRawText")
            and field not in initial
            and field not in final_state
            and current.get(field) == ""
        )
    for field in source.get("unresolvedSourceFields", []):
        reason(field, "source_timeline_unresolved", "The source metadata explicitly marks this field as unresolved.")
    if source.get("nativeTagsTimelineStatus") == "partial":
        reason("nativeTags", "native_tag_timeline_partial", "Only the observed native Tag snapshots are known.")

    for day in dates[1:]:
        event = source[day]
        if not isinstance(event, dict) or not isinstance(event.get("changes", {}), dict):
            raise ValueError(f"{source['id']}: malformed event {day}")
        old_state = copy.deepcopy(state)
        for field, value in event.get("changes", {}).items():
            if field in HISTORY_FIELDS and field not in state and field in applicable_history_fields(state):
                reason(field, "legacy_cannot_remove_newly_added_field",
                       "The legacy history shape can assign a value but cannot express its earlier absence.")
            state[field] = copy.deepcopy(value)
            field_dates.setdefault(field, []).append(day)
        for field in event.get("remove", []):
            if field not in state:
                if field in HISTORY_FIELDS and field in applicable_history_fields(old_state):
                    reason(field, "event_removes_absent_field", "A dated removal refers to a field absent in the prior state.")
            else:
                state.pop(field)
                field_dates.setdefault(field, []).append(day)
        tags = {x["id"]: copy.deepcopy(x) for x in state.get("nativeTags", [])}
        for item in event.get("nativeTagUpdates", []):
            tags[item["id"]] = {"id": item["id"], "value": item["value"]}
        for tag_id in event.get("nativeTagRemovals", []):
            tags.pop(tag_id, None)
        if "nativeTagUpdates" in event or "nativeTagRemovals" in event:
            state["nativeTags"] = [tags[k] for k in sorted(tags)]
            reason("nativeTags", "native_tag_history_not_exposed_in_legacy_api",
                   "Numeric Tag observations are preserved in dated source events, not the legacy history schema.")
        snapshots.append((day, copy.deepcopy(state)))

    current = source["current"]
    final_state = snapshots[-1][1]
    revisions = []
    for index, (day, snapshot) in enumerate(snapshots[:-1]):
        before = snapshots[index + 1][0]
        changes = {}
        for field in applicable_history_fields(snapshot):
            if field not in applicable_history_fields(current):
                continue
            if field in snapshot:
                if field not in current or snapshot[field] != current[field]:
                    changes[field] = copy.deepcopy(snapshot[field])
            elif field in current:
                if empty_text_projection(field):
                    compatibility[field] = {
                        "kind": "legacy_empty_string_for_absent_cardtext_tag",
                        "value": "",
                        "note": "The launch CardDefs has no CARDTEXT_INHAND value; current empty string is a compatibility projection, not a dated text change."
                    }
                elif field == "collectible" and current.get(field) is False and 321 not in initial_tags:
                    compatibility[field] = {
                        "kind": "legacy_boolean_without_native_tag",
                        "value": False,
                        "note": "The launch CardDefs has no COLLECTIBLE Tag; current false is not backfilled into the launch state."
                    }
                elif field == "spellSchool" and current.get(field) == "":
                    compatibility[field] = {
                        "kind": "legacy_empty_default",
                        "value": "",
                        "note": "An empty compatibility cache value is not treated as a dated native spell-school assignment."
                    }
                else:
                    reason(field, "legacy_cannot_remove_current_field",
                           "The historical state lacks this property, but legacy history cannot express property removal.")
        if changes:
            revisions.append({"from": day, "before": before, "changes": changes})

    replay_mismatches = {}
    for field in applicable_history_fields(final_state):
        if field not in applicable_history_fields(current):
            continue
        if field in final_state and field in current and final_state[field] != current[field]:
            replay_mismatches[field] = {
                "datedReplay": copy.deepcopy(final_state[field]),
                "current": copy.deepcopy(current[field]),
                "transitionDate": None,
                "note": "Dated events do not reconcile this canonical field with current; both observations are preserved."
            }
            reason(field, "dated_replay_current_mismatch",
                   "The final dated canonical state differs from the current canonical state.")
        elif (field in final_state) != (field in current):
            if empty_text_projection(field):
                compatibility[field] = {
                    "kind": "legacy_empty_string_for_absent_cardtext_tag",
                    "value": "",
                    "note": "The launch CardDefs has no CARDTEXT_INHAND value; current empty string is a compatibility projection, not a dated text change."
                }
            elif field == "collectible" and current.get(field) is False and 321 not in initial_tags:
                compatibility[field] = {
                    "kind": "legacy_boolean_without_native_tag",
                    "value": False,
                    "note": "The launch CardDefs has no COLLECTIBLE Tag; current false is not backfilled into the launch state."
                }
            elif field == "spellSchool" and current.get(field) == "":
                compatibility[field] = {
                    "kind": "legacy_empty_default",
                    "value": "",
                    "note": "An empty compatibility cache value is not treated as a dated native spell-school assignment."
                }
            else:
                replay_mismatches[field] = {
                    "datedReplayPresent": field in final_state,
                    "currentPresent": field in current,
                    "transitionDate": None,
                    "note": "Canonical field presence differs after replay; absence is not converted to a default."
                }
                reason(field, "dated_replay_current_presence_mismatch",
                       "The final dated canonical state and current state disagree about field presence.")

    for field in ("armor", "durability", "spellSchool", "health", "race", "races"):
        if field in current and field not in applicable_history_fields(current):
            compatibility[field] = {
                "kind": "legacy_projection_or_type_inapplicable",
                "value": copy.deepcopy(current[field]),
                "note": "Preserved in the current compatibility cache; omitted from canonical historical state for this card type."
            }

    timeline = {}
    for field in ("name", "text", "nativeRawText", "nativeTextBuilder"):
        launch_state = snapshot_field(initial, field)
        dated_state = snapshot_field(final_state, field)
        current_state = snapshot_field(current, field)
        if empty_text_projection(field):
            compatibility[field] = {
                "kind": "legacy_empty_string_for_absent_cardtext_tag",
                "value": "",
                "note": "The launch CardDefs has no CARDTEXT_INHAND value; current empty string is a compatibility projection, not a dated text change."
            }
            continue
        if dated_state != current_state:
            timeline[field] = {
                "launch": launch_state,
                "afterDatedEvents": dated_state,
                "current": current_state,
                "datedEventDates": sorted(set(field_dates.get(field, []))),
                "transitionDate": None,
                "note": "Only the remaining launch-to-current difference is undated; dated event changes have already been replayed."
            }

    if replay_mismatches:
        source["historyReplayMismatches"] = replay_mismatches
    else:
        source.pop("historyReplayMismatches", None)
    if reasons:
        normalized = {field: sorted(items, key=lambda x: (x["code"], x["detail"])) for field, items in sorted(reasons.items())}
        source["historyIncompleteReasons"] = normalized
        source["historyIncompleteFields"] = sorted(normalized)
    else:
        source.pop("historyIncompleteReasons", None)
        source.pop("historyIncompleteFields", None)
    if compatibility:
        source["historyCompatibilityLimits"] = compatibility
    else:
        source.pop("historyCompatibilityLimits", None)
    if timeline:
        source["timelineIncompleteFields"] = timeline
    else:
        source.pop("timelineIncompleteFields", None)
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
        original_source = copy.deepcopy(source)
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
        # Normalize every exported change map at the serialization boundary too.
        # This protects render/history JSON from any upstream mapping/set order.
        for revision in revisions:
            revision["changes"] = {
                field: revision["changes"][field]
                for field in HISTORY_FIELDS
                if field in revision["changes"]
            }
        event_count += len([k for k in source if DATE_RE.fullmatch(k)]) - 1
        incomplete_counts.update(source.get("historyIncompleteFields", []))
        render_card = {field: copy.deepcopy(record[field]) for field in RENDER_FIELDS if field in record}
        if revisions:
            render_card["history"] = revisions
            history[str(record["dbfId"])] = {"id": cid, "history": revisions}
        renderer.append(render_card)
        if write and source != original_source:
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
