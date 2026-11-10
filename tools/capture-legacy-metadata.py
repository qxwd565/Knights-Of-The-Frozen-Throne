#!/usr/bin/env python3
"""Capture and verify the eight stable top-level metadata fields before migration."""
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("root", "relatedIds", "englishName", "expansion", "setOrder", "formats", "provenance", "mode")

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def git_json(commit, path):
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)

def main(commit):
    current_paths = sorted((ROOT / "data").glob("ICC_*.json"))
    if len(current_paths) != 182:
        raise RuntimeError(f"Expected 182 current data files, found {len(current_paths)}")
    cards = {}
    legacy_patches = {}
    counts = {field: 0 for field in FIELDS}
    for path in current_paths:
        cid = path.stem
        before = git_json(commit, f"data/{cid}.json")
        after = load(path)
        metadata = {field: before[field] for field in FIELDS if field in before}
        old_card = before.get("card", {})
        legacy_patches[cid] = copy.deepcopy(old_card.get("patches", []))
        for field, value in metadata.items():
            counts[field] += 1
            if field not in after:
                raise RuntimeError(f"{cid}: lost stable metadata field {field}")
            if after[field] != value:
                raise RuntimeError(f"{cid}: stable metadata changed for {field}")
        cards[cid] = metadata
    if any(count == 0 for count in counts.values()):
        raise RuntimeError(f"Metadata baseline unexpectedly empty: {counts}")
    manifest = {
        "schema": 1,
        "sourceCommit": commit,
        "fields": list(FIELDS),
        "cards": cards,
        "legacyPatches": legacy_patches,
        "legacyPatchEventCount": sum(len(x) for x in legacy_patches.values()),
        "counts": counts,
    }
    out = ROOT / "sources" / "legacy-metadata-baseline.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cards": len(cards), "counts": counts, "sourceCommit": commit}, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: capture-legacy-metadata.py <baseline-commit>")
    main(sys.argv[1])
