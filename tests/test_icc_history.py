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
            self.assertIn("initialSpecStatus", item)
            self.assertIn("patchSources", item)
            self.assertEqual(sorted(k for k in item if BUILD.DATE_RE.fullmatch(k))[0], "2017-08-11")
            for field in stable:
                self.assertIn(field, item, f"{path.stem}:{field}")
            self.assertIsInstance(item["root"], bool, path.stem)
            self.assertIsInstance(item["relatedIds"], list, path.stem)

    def test_all_stable_metadata_matches_the_pre_v2_source_commit(self):
        manifest = BUILD.load(ROOT / "sources" / "legacy-metadata-baseline.json")
        self.assertEqual(
            manifest["sourceCommit"],
            "9dd6b844daa08ceffd171e090e001ae3de36c3ec",
        )
        self.assertEqual(len(manifest["cards"]), 182)
        for cid, expected_fields in manifest["cards"].items():
            item = source(cid)
            for field, expected in expected_fields.items():
                self.assertIn(field, item, f"{cid}:{field}")
                self.assertEqual(item[field], expected, f"{cid}:{field}")

    def test_all_111_legacy_patch_events_are_retained(self):
        manifest = BUILD.load(ROOT / "sources" / "legacy-metadata-baseline.json")
        self.assertEqual(manifest["legacyPatchEventCount"], 111)
        for cid, patches in manifest["legacyPatches"].items():
            item = source(cid)
            for patch in patches:
                day = patch["date"]
                self.assertIn(day, item, f"{cid}:{day}")
                for field, old_value in patch["changes"].items():
                    expected = old_value
                    if cid == "ICC_705" and day == "2022-11-30" and field == "races":
                        expected = ["UNDEAD", "BEAST"]
                    self.assertIn(field, item[day]["changes"], f"{cid}:{day}:{field}")
                    self.assertEqual(item[day]["changes"][field], expected, f"{cid}:{day}:{field}")

    def test_all_current_raw_text_and_native_tags_match_pre_migration_sources(self):
        manifest = BUILD.load(ROOT / "sources" / "legacy-metadata-baseline.json")
        self.assertEqual(len(manifest["rawSources"]), 182)
        for cid, fields in manifest["rawSources"].items():
            current = source(cid)["current"]
            for field, expected in fields.items():
                self.assertIn(field, current, f"{cid}:{field}")
                self.assertEqual(current[field], expected, f"{cid}:{field}")

    def test_launch_carddefs_snapshot_has_exact_ids_and_dbf_mappings(self):
        baseline = BUILD.load(ROOT / "sources" / "carddefs-9.0.0.20457-baseline.json")
        catalog = BUILD.load(ROOT / "cards.json")
        records = {x["id"]: x for x in catalog["cards"]}
        for cid, original in baseline["cards"].items():
            self.assertEqual(original["dbfId"], records[cid]["dbfId"], cid)
            self.assertIsInstance(original["nativeTags"], list, cid)
            self.assertIsInstance(original["referenceTags"], list, cid)

    def test_47_noncollectible_cards_keep_absence_distinct_from_false(self):
        catalog = BUILD.load(ROOT / "cards.json")
        baseline = BUILD.load(ROOT / "sources" / "carddefs-9.0.0.20457-baseline.json")
        records = [x for x in catalog["cards"] if x.get("collectible") is False]
        self.assertEqual(len(records), 47)
        for record in records:
            item = source(record["id"])
            initial = item["2017-08-11"]
            self.assertNotIn(321, [x["id"] for x in baseline["cards"][record["id"]]["nativeTags"]])
            self.assertNotIn("collectible", initial, record["id"])
            self.assertIs(item["current"]["collectible"], False, record["id"])

    def test_nine_card_twelve_operation_history_is_present(self):
        a = source("ICC_832t3")
        self.assertEqual(a["2017-08-11"]["cost"], 2)
        self.assertEqual(a["2017-12-07"]["changes"]["cost"], 1)
        self.assertIn("https://hearthstone.blizzard.com/ko-kr/news/21274279", a["2017-12-07"]["sources"])

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
        self.assertTrue(a["2025-05-23"]["sources"])

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
        self.assertNotIn("race", a["2017-08-11"])
        self.assertNotIn("races", a["2017-08-11"])
        self.assertIn("spellSchool", a["2018-11-30"]["remove"])
        self.assertEqual(b["2017-08-11"]["type"], "SPELL")
        self.assertEqual(b["2018-11-30"]["changes"]["health"], 5)
        self.assertEqual(b["2018-11-30"]["changes"]["text"], "<b>도발</b>")

    def test_reference_tags_are_separate_from_owned_raw_tags(self):
        item = source("ICC_221")
        self.assertIn(685, [x["id"] for x in item["2017-08-11"]["referenceTags"]])
        ref = next(x for x in item["2017-08-11"]["referenceTags"] if x["id"] == 685)
        self.assertEqual(ref["sourceType"], "ReferencedTag")
        self.assertEqual(ref["label"], "생명력 흡수")
        self.assertNotIn(685, [x["id"] for x in item["2017-08-11"]["nativeTags"]])
        self.assertIn(685, [x["id"] for x in item["current"]["referenceTags"]])
        # Preserve the old source array exactly in current; the separate list
        # records that its origin was a ReferencedTag, not an owned Tag.
        self.assertTrue(any(x["id"] == 685 for x in item["current"]["nativeTags"]))

    def test_sparse_event_add_remove_and_falsy_values_are_distinct(self):
        state = {
            "cost": 0, "collectible": False, "text": None,
            "race": "", "races": [], "nativeTags": [{"id": 48, "value": 0}],
        }
        reverse, incomplete = BUILD.apply_sparse_event(
            state,
            {
                "changes": {"cost": 1},
                "remove": ["race"],
                "nativeTagUpdates": [{"id": 48, "value": 2}, {"id": 45, "value": 1}],
                "nativeTagRemovals": [45],
            },
        )
        self.assertEqual(state["cost"], 1)
        self.assertIs(state["collectible"], False)
        self.assertIsNone(state["text"])
        self.assertEqual(state["races"], [])
        self.assertNotIn("race", state)
        self.assertEqual(reverse["cost"], 0)
        self.assertEqual(reverse["race"], "")
        self.assertEqual(state["nativeTags"], [{"id": 48, "value": 2}])
        self.assertIn("nativeTags", incomplete)
        self.assertIn("race", incomplete)

        added = {"cost": 2}
        reverse, incomplete = BUILD.apply_sparse_event(
            added, {"changes": {"spellSchool": "SHADOW"}}
        )
        self.assertEqual(reverse, {})
        self.assertIn("spellSchool", incomplete)

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
        self.assertEqual(result["dateEvents"], 142)
        self.assertGreater(result["datedCards"], 100)
        render = BUILD.load(ROOT / "render.json")
        legacy_history = BUILD.load(ROOT / "history.json")
        self.assertEqual(render["schema"], 1)
        self.assertEqual(legacy_history["schema"], 1)
        rendered = {x["id"]: x for x in render["cards"]}
        self.assertEqual(len(rendered), 182)
        for cid, record in records.items():
            self.assertIn(cid, rendered)
            for field in BUILD.RENDER_FIELDS:
                if field in record:
                    self.assertEqual(rendered[cid].get(field), record[field], f"{cid}:{field}")
        for dbf_id, entry in legacy_history["cards"].items():
            self.assertEqual(records[entry["id"]]["dbfId"], int(dbf_id))
        for card in render["cards"]:
            dbf_id = str(records[card["id"]]["dbfId"])
            if "history" in card:
                self.assertIn(dbf_id, legacy_history["cards"])
                self.assertEqual(card["history"], legacy_history["cards"][dbf_id]["history"])


    def test_launch_strings_match_the_immutable_fixture_for_all_182_cards(self):
        fixture = BUILD.load(ROOT / "sources" / "carddefs-9.0.0.20457-baseline.json")
        self.assertEqual(len(fixture["cards"]), 182)
        for cid, original in fixture["cards"].items():
            launch = source(cid)["2017-08-11"]
            strings = original["localizedStrings"]
            name = strings["CARDNAME"]
            ko_name = name["locales"]["koKR"]
            self.assertTrue(name["tagPresent"], cid)
            self.assertTrue(ko_name["present"], cid)
            self.assertEqual(launch["name"], ko_name["nativeRawText"], cid)
            text = strings["CARDTEXT_INHAND"]
            ko_text = text["locales"]["koKR"]
            if text["tagPresent"] and ko_text["present"]:
                self.assertIn("nativeRawText", launch, cid)
                self.assertEqual(launch["nativeRawText"], ko_text["nativeRawText"], cid)
                expected_display = "" if cid == "ICC_828t" else ko_text["nativeRawText"].replace("[x]", "").replace(chr(10), "<br></br>")
                self.assertEqual(launch["text"], expected_display, cid)
            else:
                self.assertNotIn("nativeRawText", launch, cid)
                self.assertNotIn("text", launch, cid)
            self.assertNotIn("nativeTextBuilder", launch, cid)

    def test_seven_archive_observation_groups_are_separate_from_balance_history(self):
        manifest = BUILD.load(ROOT / "sources" / "frozen-throne-observation-evidence.json")
        self.assertEqual(len(manifest["findings"]), 7)
        self.assertEqual({x["findingID"] for x in manifest["findings"]},
                         {"FT-D01", "FT-D05", "FT-D06", "FT-D07", "FT-D08", "FT-D13", "FT-D19"})
        observed_rows = set()
        for finding in manifest["findings"]:
            self.assertFalse(finding["countedAsConfirmedGameplayHistory"])
            self.assertEqual(finding["classification"], "observed_archive_change_not_confirmed_gameplay_delta")
            self.assertIn(finding["archiveBefore"]["url"], finding["sourceURLs"])
            self.assertIn(finding["archiveAfter"]["url"], finding["sourceURLs"])
            for observation in finding["observations"]:
                cid, day = observation["cardID"], finding["koreanDay"]
                observed_rows.add((cid, day))
                event = source(cid)[day]
                self.assertEqual(event["classification"], finding["classification"])
                evidence = next(x for x in event["sourceEvidence"] if x["findingID"] == finding["findingID"])
                self.assertFalse(evidence["countedAsConfirmedGameplayHistory"])
                self.assertEqual(evidence["archiveBefore"], finding["archiveBefore"])
                self.assertEqual(evidence["archiveAfter"], finding["archiveAfter"])
                for key, expected in observation["changes"].items():
                    if key.isdigit():
                        tag_id = int(key)
                        if expected["after"]["present"]:
                            update = next(x for x in event.get("nativeTagUpdates", []) if x["id"] == tag_id)
                            self.assertEqual(update["value"], int(expected["after"]["value"]), f"{cid}:{day}:Tag{tag_id}")
                            self.assertNotIn(tag_id, event.get("nativeTagRemovals", []))
                        else:
                            self.assertIn(tag_id, event.get("nativeTagRemovals", []), f"{cid}:{day}:Tag{tag_id}")
                    elif key == "rawText":
                        self.assertEqual(event["changes"]["nativeRawText"], expected["after"], cid)
                        self.assertEqual(event["changes"]["text"], expected["after"].replace("[x]", "").replace(chr(10), "<br></br>"), cid)
            for url in finding["sourceURLs"]:
                self.assertTrue(all(url in source(ob["cardID"])[finding["koreanDay"]]["sources"]
                                    for ob in finding["observations"]))
        self.assertEqual(len(observed_rows), 18)
        self.assertIn("rarity", source("ICC_829t2")["2017-12-07"]["remove"])
        self.assertEqual(source("ICC_856")["2024-10-30"]["nativeTagUpdates"], [{"id": 192, "value": 1}])
        self.assertEqual(source("ICC_064")["2025-03-19"]["nativeTagUpdates"], [{"id": 45, "value": 2}])
        self.assertEqual(source("ICC_064")["2025-03-19"]["nativeTagRemovals"], [187])

    def test_dated_text_replay_clears_resolved_launch_differences(self):
        for cid in ("ICC_047t2", "ICC_051b", "ICC_405", "ICC_408"):
            item = source(cid)
            BUILD.replay_legacy(item, item["current"])
            timeline = item.get("timelineIncompleteFields", {})
            self.assertNotIn("text", timeline, cid)
            self.assertNotIn("nativeRawText", timeline, cid)
        b = source("ICC_051b")
        BUILD.replay_legacy(b, b["current"])
        self.assertNotIn("text", b.get("timelineIncompleteFields", {}))
        self.assertIn("nativeTextBuilder", b.get("timelineIncompleteFields", {}))
        self.assertNotIn("spellSchool", b.get("historyReplayMismatches", {}))
        self.assertNotIn("durability", b.get("historyReplayMismatches", {}))
        self.assertNotIn("durability", b.get("historyIncompleteFields", []))
        self.assertIn("collectible", b.get("historyCompatibilityLimits", {}))

    def test_launch_strings_are_applied_without_rewriting_current_observations(self):
        fixture = BUILD.load(ROOT / "sources" / "carddefs-9.0.0.20457-baseline.json")
        self.assertEqual(len(fixture["cards"]), 182)
        self.assertEqual(source("ICC_051b")["2017-08-11"]["text"], "생명력 +3, <b>도발</b>")
        self.assertEqual(source("ICC_055")["2017-08-11"]["nativeRawText"],
                         "<b>생명력 흡수</b>\n하수인 하나에게\n피해를 $2 줍니다.")
        self.assertIn("부여하고 피해를 3", source("ICC_047t2")["2017-08-11"]["text"])
        zombeast = source("ICC_828t")
        self.assertEqual(zombeast["2017-08-11"]["nativeRawText"], "{0}, {1}")
        self.assertEqual(zombeast["2017-08-11"]["text"], "")
        self.assertEqual(zombeast["current"]["text"], "")
        self.assertEqual(source("ICC_314t2")["2017-08-11"]["name"], "사자의 군대")
        self.assertEqual(source("ICC_827p")["2017-08-11"]["name"], "죽음의 그림자")
        self.assertEqual(source("ICC_829t4")["2017-08-11"]["name"], "종교재판관 화이트메인")

    def test_legacy_intervals_restore_all_known_fields_not_only_next_event_fields(self):
        cases = {
            "ICC_235": ("2017-08-11", {"cost": 6}),
            "ICC_910": ("2017-08-11", {"cost": 6}),
            "ICC_705": ("2017-08-11", {"races": []}),
            "ICC_466": ("2021-03-26", {"text": "<b>도발</b>, <b>전투의 함성:</b><br></br>이 하수인을 복사하여 소환합니다."}),
        }
        for cid, (start, expected) in cases.items():
            item = source(cid)
            revisions = BUILD.replay_legacy(item, item["current"])
            revision = next(x for x in revisions if x["from"] == start)
            for field, value in expected.items():
                self.assertEqual(revision["changes"].get(field), value, f"{cid}:{start}:{field}")
        self.assertEqual(source("ICC_235")["current"]["cost"], 7)
        self.assertEqual(source("ICC_910")["current"]["cost"], 5)

        for cid in ("ICC_051b", "ICC_055"):
            item = source(cid)
            BUILD.replay_legacy(item, item["current"])
            mismatches = item.get("historyReplayMismatches", {})
            self.assertNotIn("durability", mismatches, cid)
            self.assertNotIn("armor", mismatches, cid)
        item = source("ICC_051b")
        BUILD.replay_legacy(item, item["current"])
        self.assertNotIn("spellSchool", item.get("historyReplayMismatches", {}))

    def test_full_known_state_is_restored_at_every_boundary_for_all_cards(self):
        paths = sorted((ROOT / "data").glob("ICC_*.json"))
        self.assertEqual(len(paths), 182)
        for path in paths:
            item = BUILD.load(path)
            dates = sorted(k for k in item if BUILD.DATE_RE.fullmatch(k))
            state = dict(item[dates[0]])
            current = item["current"]
            revisions = BUILD.replay_legacy(item, current)
            for index, day in enumerate(dates[:-1]):
                if index:
                    BUILD.apply_sparse_event(state, item[day])
                before = dates[index + 1]
                revision = next((x for x in revisions if x["from"] == day and x["before"] == before), None)
                changes = revision["changes"] if revision else {}
                fields = BUILD.applicable_history_fields(state) & BUILD.applicable_history_fields(current)
                for field in fields:
                    if field in state and field in current:
                        if state[field] != current[field]:
                            self.assertEqual(changes.get(field), state[field], f"{path.stem}:{day}:{field}")
                        else:
                            self.assertNotIn(field, changes, f"{path.stem}:{day}:{field}")
                    elif field not in state and field in current:
                        self.assertIn(field, item.get("historyIncompleteFields", []),
                                      f"{path.stem}:{day}:{field}")

if __name__ == "__main__":
    unittest.main(verbosity=2)
