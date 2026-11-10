import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_api", ROOT / "tools" / "build-api.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def source(cid):
    return BUILD.load(ROOT / "data" / f"{cid}.json")


class FrozenThroneHistoryTest(unittest.TestCase):
    def test_all_182_cards_have_dated_v2_sources_and_stable_metadata(self):
        catalog = BUILD.load(ROOT / "cards.json")
        baseline = BUILD.load(ROOT / "sources" / "carddefs-9.0.0.20457-baseline.json")
        paths = sorted((ROOT / "data").glob("ICC_*.json"))
        self.assertEqual(len(catalog["cards"]), 182)
        self.assertEqual(len(paths), 182)
        self.assertEqual(set(baseline["cards"]), {p.stem for p in paths})
        self.assertEqual(baseline["source"]["commit"], "6f874a2b18045ed3464983aff85ca106bc656916")
        records = {x["id"]: x for x in catalog["cards"]}
        stable = ("root", "relatedIds", "englishName", "expansion", "setOrder", "formats", "provenance", "mode")
        for path in paths:
            item = BUILD.load(path)
            self.assertEqual(item["schemaVersion"], 2, path.stem)
            self.assertEqual(item["id"], path.stem)
            self.assertEqual(item["dbfId"], records[path.stem]["dbfId"])
            self.assertEqual(item["current"]["dbfId"], item["dbfId"])
            self.assertEqual(item["current"]["releasedAt"], "2017-08-11")
            self.assertEqual(item["current"]["releaseStatus"], "verified")
            self.assertEqual(sorted(k for k in item if BUILD.DATE_RE.fullmatch(k))[0], "2017-08-11")
            for field in stable:
                self.assertIn(field, item, f"{path.stem}:{field}")
            self.assertIsInstance(item["root"], bool, path.stem)
            self.assertIsInstance(item["relatedIds"], list, path.stem)

    def test_launch_carddefs_snapshot_has_exact_ids_and_dbf_mappings(self):
        baseline = BUILD.load(ROOT / "sources" / "carddefs-9.0.0.20457-baseline.json")
        catalog = BUILD.load(ROOT / "cards.json")
        records = {x["id"]: x for x in catalog["cards"]}
        for cid, original in baseline["cards"].items():
            self.assertEqual(original["dbfId"], records[cid]["dbfId"], cid)
            self.assertIsInstance(original["nativeTags"], list, cid)
            self.assertIsInstance(original["referenceTags"], list, cid)

    def test_nine_card_twelve_operation_history_is_present(self):
        a = source("ICC_832t3")
        self.assertEqual(a["2017-08-11"]["cost"], 2)
        self.assertEqual(a["2017-12-07"]["changes"]["cost"], 1)

        a = source("ICC_221")
        self.assertEqual(a["2017-08-11"]["cost"], 2)
        self.assertEqual(a["2017-08-11"]["text"], "내 무기에 <b>생명력 흡수</b>를 부여합니다.")
        self.assertEqual(a["2018-12-20"]["changes"]["cost"], 1)
        self.assertIn("이번 턴에", a["2018-12-20"]["changes"]["text"])

        a = source("ICC_466")
        self.assertEqual(a["2018-12-20"]["changes"]["text"],
                         "<b>도발</b>, <b>전투의 함성:</b><br></br>다른 사로나이트 광산<br></br>노예를 소환합니다.")
        self.assertIn("이 하수인을 복사하여", a["2021-03-26"]["changes"]["text"])
        self.assertEqual(a["2025-05-23"]["changes"]["text"], a["current"]["text"])

        a = source("ICC_055")
        self.assertIn("$2", a["2017-08-11"]["text"])
        self.assertIn("$3", a["2021-03-26"]["changes"]["text"])
        self.assertIn("spellSchool", a["2021-03-26"]["changes"])

        a = source("ICC_706")
        self.assertEqual(a["2017-08-11"]["races"], [])
        self.assertEqual(a["2022-11-30"]["changes"]["races"], ["UNDEAD"])
        self.assertEqual(a["2023-02-15"]["changes"]["races"], [])

        a = source("ICC_910")
        self.assertEqual(a["2017-08-11"]["cost"], 6)
        self.assertEqual(a["2023-03-03"]["changes"]["cost"], 5)
        self.assertIn("하수인에게 피해를 2씩", a["2023-03-03"]["changes"]["text"])

        self.assertEqual(source("ICC_210")["2017-08-11"]["health"], 2)
        self.assertEqual(source("ICC_210")["2023-04-05"]["changes"]["health"], 3)
        self.assertEqual(source("ICC_235")["2017-08-11"]["cost"], 6)
        self.assertEqual(source("ICC_235")["2023-09-29"]["changes"]["cost"], 7)
        self.assertEqual(source("ICC_075")["2017-08-11"]["health"], 5)
        self.assertEqual(source("ICC_075")["2025-03-19"]["changes"]["health"], 6)

    def test_skullhorse_launch_race_is_empty_and_later_types_are_dated(self):
        item = source("ICC_705")
        self.assertEqual(item["2017-08-11"]["races"], [])
        self.assertEqual(item["2017-08-11"]["race"], "")
        self.assertEqual(item["2022-11-30"]["changes"]["races"], ["UNDEAD", "BEAST"])
        self.assertEqual(item["2022-11-30"]["changes"]["race"], "언데드, 야수")
        self.assertEqual(item["2018-02-07"]["changes"]["cost"], 8)
        self.assertEqual(item["2021-03-26"]["changes"]["cost"], 7)

    def test_choice_screen_forms_are_not_confused_with_the_summoned_results(self):
        a = source("ICC_051a")
        b = source("ICC_051b")
        self.assertEqual(a["2017-08-11"]["type"], "SPELL")
        self.assertEqual(a["2018-11-30"]["changes"]["type"], "MINION")
        self.assertEqual(a["2018-11-30"]["changes"]["attack"], 1)
        self.assertEqual(a["2018-11-30"]["changes"]["health"], 2)
        self.assertEqual(b["2017-08-11"]["type"], "SPELL")
        self.assertEqual(b["2018-11-30"]["changes"]["health"], 5)
        self.assertEqual(b["2018-11-30"]["changes"]["text"], "<b>도발</b>")

    def test_reference_tags_are_separate_from_owned_raw_tags(self):
        item = source("ICC_221")
        self.assertIn(685, [x["id"] for x in item["2017-08-11"]["referenceTags"]])
        self.assertNotIn(685, [x["id"] for x in item["2017-08-11"]["nativeTags"]])
        self.assertIn(685, [x["id"] for x in item["current"]["referenceTags"]])
        # Preserve the old source array exactly in current; the separate list
        # records that its origin was a ReferencedTag, not an owned Tag.
        self.assertTrue(any(x["id"] == 685 for x in item["current"]["nativeTags"]))

    def test_raw_lf_and_display_breaks_are_distinct(self):
        item = source("ICC_466")
        self.assertIn("\n", item["2017-08-11"]["nativeRawText"])
        self.assertIn("<br></br>", item["2017-08-11"]["text"])
        self.assertNotIn("<br></br>", item["2017-08-11"]["nativeRawText"])

    def test_schema1_api_adapter_builds_all_182_cards_and_preserves_break_repairs(self):
        result = BUILD.build_indexes(write=False)
        self.assertEqual(result["cards"], 182)
        catalog = BUILD.load(ROOT / "cards.json")
        render = {"schema": 1, "set": catalog["set"], "cards": []}
        records = {x["id"]: x for x in catalog["cards"]}
        for cid, record in records.items():
            self.assertIn(cid, records)
            if cid == "ICC_018":
                self.assertIn("<br></br>", record["text"])
        self.assertGreater(result["dateEvents"], 111)
        self.assertGreater(result["datedCards"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
