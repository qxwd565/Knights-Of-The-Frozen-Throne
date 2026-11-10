#!/usr/bin/env python3
import json
import sys
import xml.etree.ElementTree as ET

targets = {"ICC_832t3", "ICC_221", "ICC_466", "ICC_055", "ICC_706", "ICC_910", "ICC_210", "ICC_235", "ICC_075", "ICC_705"}
found = {}
for _, element in ET.iterparse(sys.argv[1], events=("end",)):
    if element.tag.rsplit("}", 1)[-1] == "Entity" and element.attrib.get("CardID") in targets:
        cid = element.attrib["CardID"]
        found[cid] = {
            "attributes": element.attrib,
            "children": [
                {"tag": child.tag.rsplit("}", 1)[-1], "attributes": child.attrib, "text": child.text}
                for child in list(element)
            ],
        }
        element.clear()
print(json.dumps(found, ensure_ascii=False))
if set(found) != targets:
    raise SystemExit(f"Missing baseline entities: {sorted(targets - set(found))}")
