#!/usr/bin/env python3
"""Extract exact koKR/enUS launch CardDefs strings for all Frozen Throne cards."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "sources" / "carddefs-9.0.0.20457-baseline.json"
LOCALES = ("koKR", "enUS")
STRING_TAGS = {
    185: "CARDNAME",
    184: "CARDTEXT_INHAND",
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_string(element):
    # XML text is retained byte-for-character after XML entity decoding.
    # The game/API raw-text convention uses real LF for the two-character
    # source escape sequence backslash+n. Keep both forms to avoid ambiguity.
    value = element.text or ""
    return {
        "present": True,
        "xmlText": value,
        "nativeRawText": value.replace("\\n", "\n"),
    }


def extract(xml_path: Path):
    baseline = load(BASELINE)
    cards = baseline["cards"]
    expected = set(cards)
    extracted = {}
    for _, entity in ET.iterparse(xml_path, events=("end",)):
        if entity.tag.rsplit("}", 1)[-1] != "Entity":
            continue
        card_id = entity.attrib.get("CardID")
        if card_id not in expected:
            entity.clear()
            continue
        localized = {}
        for child in list(entity):
            if child.tag.rsplit("}", 1)[-1] != "Tag":
                continue
            try:
                enum_id = int(child.attrib.get("enumID", "-1"))
            except ValueError:
                continue
            if enum_id not in STRING_TAGS:
                continue
            field = STRING_TAGS[enum_id]
            locales = {}
            for locale in LOCALES:
                locale_node = next(
                    (node for node in list(child)
                     if node.tag.rsplit("}", 1)[-1] == locale),
                    None,
                )
                locales[locale] = (
                    source_string(locale_node) if locale_node is not None
                    else {"present": False}
                )
            localized[field] = {
                "tagPresent": True,
                "locales": locales,
            }
        for field in STRING_TAGS.values():
            localized.setdefault(field, {
                "tagPresent": False,
                "locales": {locale: {"present": False} for locale in LOCALES},
            })
        extracted[card_id] = localized
        entity.clear()

    missing = expected - set(extracted)
    extra = set(extracted) - expected
    if missing or extra or len(extracted) != 182:
        raise RuntimeError(
            f"Expected exact 182-card extraction; found={len(extracted)}, "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )

    counts = {
        field: {
            locale: {
                "tagPresent": sum(
                    item[field]["tagPresent"] for item in extracted.values()
                ),
                "valuePresent": sum(
                    item[field]["locales"][locale]["present"]
                    for item in extracted.values()
                ),
                "empty": sum(
                    item[field]["locales"][locale]["present"]
                    and item[field]["locales"][locale].get("xmlText") == ""
                    for item in extracted.values()
                ),
            }
            for locale in LOCALES
        }
        for field in STRING_TAGS.values()
    }

    for card_id, fields in extracted.items():
        cards[card_id]["localizedStrings"] = fields

    baseline["localizedStringExtraction"] = {
        "sourceCommit": baseline["source"]["commit"],
        "sourcePath": "CardDefs.xml",
        "locales": list(LOCALES),
        "fields": STRING_TAGS,
        "representation": {
            "xmlText": "Exact parsed XML locale text; literal backslash+n remains two characters.",
            "nativeRawText": "Same source value with literal backslash+n converted to an actual LF.",
            "presence": "tagPresent and locale present distinguish absent tags/locales from present empty strings.",
        },
        "counts": counts,
        "cardCount": len(extracted),
    }
    BASELINE.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "cards": len(extracted),
        "nameKoKR": sum(x["CARDNAME"]["locales"]["koKR"]["present"] for x in extracted.values()),
        "nameEnUS": sum(x["CARDNAME"]["locales"]["enUS"]["present"] for x in extracted.values()),
        "textKoKR": sum(x["CARDTEXT_INHAND"]["locales"]["koKR"]["present"] for x in extracted.values()),
        "textEnUS": sum(x["CARDTEXT_INHAND"]["locales"]["enUS"]["present"] for x in extracted.values()),
        "textKoKREmpty": counts["CARDTEXT_INHAND"]["koKR"]["empty"],
        "textEnUSEmpty": counts["CARDTEXT_INHAND"]["enUS"]["empty"],
        "metadata": baseline["localizedStringExtraction"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: extract-icc-launch-strings.py /path/to/CardDefs.xml")
    extract(Path(sys.argv[1]))
