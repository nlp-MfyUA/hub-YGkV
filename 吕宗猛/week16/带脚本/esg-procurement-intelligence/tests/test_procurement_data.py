"""Behavior checks for procurement amounts, versioning, statistics and monitoring."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "procurement_data.py"
SPEC = importlib.util.spec_from_file_location("procurement_data", SCRIPT)
DATA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DATA)


def money(value="84.2", unit="万元", kind="award", **overrides):
    output = {"kind": kind, "raw": str(value) + unit, "value": value, "unit": unit,
              "currency": "CNY", "tax_basis": "unspecified", "scope": "lot_total"}
    output.update(overrides)
    return output


def notice(record_id="n1", **overrides):
    output = {"record_id": record_id, "project_number": "P1", "buyer": "采购人甲",
              "lot_id": "whole", "procurement_round": "1", "title": "碳核算技术服务",
              "category": "service", "region": "广东", "notice_type": "award",
              "status": "awarded", "published_date": "2026-10-30", "award_date": None,
              "revision": 1, "source_id": "s1", "verification": "verified",
              "inclusion_reason": "明确的碳核算工作", "winners": ["供应商甲"],
              "evidence": [{"source_id": "s1", "locator": "正文金额段", "excerpt": "成交价84.2万元"}],
              "amounts": [money()]}
    output.update(overrides)
    return output


def document(records, **coverage):
    return {"records": records,
            "sources": [{"source_id": "s1", "url": "https://example.org/notice/1",
                         "publisher": "测试采购门户", "status": "ok", "checked_at": "2026-11-25T09:00:00+08:00"}],
            "coverage": {"regions_requested": "中国全国", "limitations": ["合成测试数据"], **coverage}}


class AmountChecks(unittest.TestCase):
    def test_decimal_units_without_float_rounding(self):
        self.assertEqual(DATA.normalize_amount(money("1.123456", "万元"))["base_amount"], "11234.560000")
        self.assertEqual(DATA.normalize_amount(money("2", "亿元"))["base_amount"], "200000000")

    def test_raw_only_exact_amount(self):
        item = money()
        item.pop("value")
        item.pop("unit")
        self.assertEqual(DATA.normalize_amount(item)["base_amount"], "842000.0")

    def test_missing_does_not_become_zero(self):
        item = DATA.normalize_amount({"kind": "award", "currency": "CNY", "scope": "lot_total"})
        self.assertIsNone(item["base_amount"])
        self.assertTrue(item["issues"])

    def test_explicit_zero_is_not_missing(self):
        item = DATA.normalize_amount(money("0", "元"))
        self.assertEqual(item["base_amount"], "0")
        self.assertFalse(item["issues"])
        self.assertEqual(DATA.normalize_amount(money(0, "元"))["base_amount"], "0")

    def test_ambiguity_and_float_are_rejected(self):
        for item in [money(raw="约84.2万元"), money(value=84.2), money("1,23", "元"),
                     money("1e5", "元"), money("-5", "元"), money(currency=""),
                     money("1", "元", raw="2元")]:
            with self.subTest(item=item):
                self.assertIsNone(DATA.normalize_amount(item)["base_amount"])

    def test_currency_conflict_is_rejected(self):
        self.assertIsNone(DATA.normalize_amount(money(raw="人民币84.2万元", currency="USD"))["base_amount"])


class NormalizationChecks(unittest.TestCase):
    def test_repost_is_one_lot_and_keeps_versions(self):
        result = DATA.normalize(document([notice(), notice("n2", published_date="2026-11-01")]))
        self.assertEqual(len(result["lots"]), 1)
        self.assertEqual(len(result["lots"][0]["versions"]), 2)
        self.assertEqual(result["lots"][0]["current"]["award_notice_published_date"], "2026-10-30")

    def test_equivalent_decimal_precision_is_not_a_conflict(self):
        result = DATA.normalize(document([notice(), notice("n2", amounts=[money("84.20")])]))
        self.assertFalse(result["lots"][0]["conflicts"])
        amount, reason = DATA.select_total(result["lots"][0]["current"], "award")
        self.assertIsNotNone(amount)
        self.assertIsNone(reason)

    def test_same_date_conflicting_amount_is_not_silently_chosen(self):
        result = DATA.normalize(document([notice(), notice("n2", amounts=[money("90")])]))
        self.assertTrue(result["lots"][0]["conflicts"])
        self.assertEqual(DATA.statistics(result, date(2026, 11, 25))["cohort"]["lot_count"], 0)

    def test_explicit_revision_resolves_same_day_correction(self):
        result = DATA.normalize(document([notice(), notice("n2", revision=2, amounts=[money("90")])]))
        self.assertFalse(result["lots"][0]["conflicts"])
        self.assertEqual(result["lots"][0]["current"]["amounts"][0]["base_amount"], "900000")

    def test_lots_rounds_and_buyers_are_not_merged(self):
        records = [notice(lot_id="A"), notice("n2", lot_id="B"),
                   notice("n3", procurement_round="2"), notice("n4", buyer="采购人乙")]
        result = DATA.normalize(document(records))
        self.assertEqual(len(result["lots"]), 4)
        self.assertEqual(len({item["project_key"] for item in result["lots"]}), 3)
        self.assertEqual(result["announcement_count"], 1)

    def test_title_similarity_cannot_supply_missing_identity(self):
        result = DATA.normalize(document([notice(project_number=""), notice("n2", project_number="")]))
        self.assertEqual(len(result["lots"]), 2)
        self.assertTrue(all(item["current"]["review_reasons"] for item in result["lots"]))

    def test_partial_correction_blocks_primary_statistics(self):
        result = DATA.normalize(document([notice(), notice("n2", published_date="2026-11-02", is_partial=True)]))
        self.assertEqual(DATA.statistics(result, date(2026, 11, 25))["cohort"]["lot_count"], 0)

    def test_source_and_evidence_are_required(self):
        result = DATA.normalize(document([notice(evidence=[])]))
        self.assertIn("unverified_original_evidence", result["lots"][0]["current"]["review_reasons"])


class StatisticChecks(unittest.TestCase):
    def test_default_published_date_includes_unknown_award_date(self):
        result = DATA.normalize(document([notice()]))
        self.assertEqual(DATA.statistics(result, date(2026, 11, 25))["cohort"]["lot_count"], 1)
        specific = DATA.statistics(result, date(2026, 11, 25), date_basis="award_date")
        self.assertEqual(specific["cohort"]["lot_count"], 0)
        self.assertEqual(specific["exclusions"][0]["reason"], "missing_award_date")

    def test_old_award_correction_does_not_move_into_window(self):
        result = DATA.normalize(document([notice(published_date="2023-11-01"),
                                          notice("n2", published_date="2026-10-30", notice_type="correction", amounts=[money("90")])]))
        self.assertEqual(DATA.statistics(result, date(2026, 11, 25))["cohort"]["lot_count"], 0)

    def test_revoked_award_is_excluded(self):
        result = DATA.normalize(document([notice(), notice("n2", published_date="2026-11-03", status="award_revoked", notice_type="revocation")]))
        self.assertEqual(DATA.statistics(result, date(2026, 11, 25))["cohort"]["lot_count"], 0)

    def test_budget_candidate_framework_contract_not_added_to_award(self):
        amounts = [money(), money("200", kind="budget"), money("100", kind="candidate_quote"),
                   money("300", kind="framework_cap", scope="framework"), money("85", kind="contract")]
        result = DATA.statistics(DATA.normalize(document([notice(amounts=amounts)])), date(2026, 11, 25))
        self.assertEqual(result["cohort"]["award"]["totals_by_currency_and_tax_basis"][0]["total"], "842000.0")
        self.assertEqual(result["cohort"]["contract"]["totals_by_currency_and_tax_basis"][0]["total"], "850000")

    def test_framework_is_not_zero_or_confirmed_award(self):
        records = [notice(amounts=[money("300", kind="framework_cap", scope="framework")]),
                   notice("n2", project_number="P2", amounts=[])]
        result = DATA.statistics(DATA.normalize(document(records)), date(2026, 11, 25))
        self.assertEqual(result["cohort"]["award"]["disclosed_lots"], 0)
        self.assertEqual(result["cohort"]["award"]["missing_lots"], 2)
        self.assertEqual(result["cohort"]["award"]["totals_by_currency_and_tax_basis"], [])

    def test_currencies_tax_layers_and_consortia_stay_separate(self):
        records = [notice(winners=["联合甲", "联合乙"]),
                   notice("n2", project_number="P2", category="equipment_engineering", amounts=[money("9000", tax_basis="included")]),
                   notice("n3", project_number="P3", category="software_data", amounts=[money("30", "base", currency="USD")]),
                   notice("n4", project_number="P4", category="mixed", amounts=[money("40", tax_basis="excluded")])]
        result = DATA.statistics(DATA.normalize(document(records)), date(2026, 11, 25))
        self.assertEqual(len(result["cohort"]["award"]["totals_by_currency_and_tax_basis"]), 4)
        self.assertEqual(set(result["layers"]), set(DATA.CATEGORIES))
        self.assertIn("联合乙 + 联合甲", result["dimensions"]["supplier_group"])
        self.assertNotIn("联合甲", result["dimensions"]["supplier_group"])

    def test_window_calendar_and_explicit_endpoints(self):
        self.assertEqual(DATA.window(date(2026, 11, 25))["start"], "2024-11-25")
        self.assertEqual(DATA.month_shift(date(2024, 2, 29), -12), date(2023, 2, 28))
        with self.assertRaises(ValueError):
            DATA.window(date(2026, 11, 25), "2026-12-01", "2026-11-01")


class MonitorChecks(unittest.TestCase):
    def tender(self, **overrides):
        return notice(notice_type="tender", status="tender", published_date="2026-11-24",
                      amounts=[money("100", kind="budget")], deadline="2026-11-27T17:00:00+08:00", **overrides)

    def test_repeat_and_repost_do_not_create_new_business_change(self):
        records = [self.tender()]
        first, state = DATA.monitor(DATA.normalize(document(records)), {}, date(2026, 11, 25))
        second, state = DATA.monitor(DATA.normalize(document(records)), state, date(2026, 11, 25))
        repost = copy.deepcopy(records[0])
        repost.update(record_id="n2", published_date="2026-11-25")
        third, _ = DATA.monitor(DATA.normalize(document(records + [repost])), state, date(2026, 11, 25))
        self.assertEqual(len(first["changes"]), 1)
        self.assertEqual(len(first["upcoming_deadlines"]), 1)
        self.assertEqual(second["changes"], [])
        self.assertEqual(second["upcoming_deadlines"], [])
        self.assertEqual(third["changes"], [])

    def test_deadline_extension_and_termination(self):
        original = self.tender()
        _, state = DATA.monitor(DATA.normalize(document([original])), {}, date(2026, 11, 25))
        later = copy.deepcopy(original)
        later.update(record_id="n2", published_date="2026-11-26", deadline="2026-12-03T17:00:00+08:00")
        updated, state = DATA.monitor(DATA.normalize(document([original, later])), state, date(2026, 11, 26))
        self.assertEqual(updated["changes"][0]["type"], "extended")
        withdrawn = copy.deepcopy(later)
        withdrawn.update(record_id="n3", published_date="2026-11-27", status="terminated")
        ended, _ = DATA.monitor(DATA.normalize(document([original, later, withdrawn])), state, date(2026, 11, 27))
        self.assertEqual(ended["changes"][0]["type"], "terminated_or_revoked")

    def test_fee_rate_ceiling_change_is_reported_without_creating_money(self):
        original = self.tender(rates=[{"kind": "ceiling", "raw": "费率最高100%",
                "value": "100", "unit": "percent", "basis": "检测收费基数", "scope": "lot"}])
        _, state = DATA.monitor(DATA.normalize(document([original])), {}, date(2026, 11, 25))
        amended = copy.deepcopy(original)
        amended.update(record_id="n2", revision=2, notice_type="correction")
        amended["rates"][0].update(value="90", raw="费率最高90%")
        updated, state = DATA.monitor(DATA.normalize(document([original, amended])), state, date(2026, 11, 25))
        self.assertEqual(len(updated["changes"]), 1)
        self.assertEqual(updated["changes"][0]["type"], "changed")
        current = updated["changes"][0]["record"]
        self.assertEqual(current["rates"][0]["normalized_value"], "90")
        self.assertEqual([a["kind"] for a in current["amounts"]], ["budget"])
        repeat, _ = DATA.monitor(DATA.normalize(document([original, amended])), state, date(2026, 11, 25))
        self.assertEqual(repeat["changes"], [])

    def test_legacy_rate_ceiling_change_is_not_lost(self):
        original = self.tender(rate_ceiling="100%")
        _, state = DATA.monitor(DATA.normalize(document([original])), {}, date(2026, 11, 25))
        amended = copy.deepcopy(original)
        amended.update(record_id="n2", revision=2, rate_ceiling="90%")
        updated, _ = DATA.monitor(DATA.normalize(document([original, amended])), state, date(2026, 11, 25))
        self.assertEqual(updated["changes"][0]["type"], "changed")

    def test_rate_precision_repost_is_unchanged_but_basis_change_is_material(self):
        original = self.tender(rates=[{"kind": "ceiling", "raw": "100%",
                "value": "100", "unit": "percent", "basis": "检测收费基数", "scope": "lot"}])
        _, state = DATA.monitor(DATA.normalize(document([original])), {}, date(2026, 11, 25))
        repost = copy.deepcopy(original)
        repost.update(record_id="n2", revision=2)
        repost["rates"][0].update(value="100.00", raw="100.00%")
        result, state = DATA.monitor(DATA.normalize(document([original, repost])), state, date(2026, 11, 25))
        self.assertEqual(result["changes"], [])
        repost.update(record_id="n3", revision=3)
        repost["rates"][0]["basis"] = "合同约定的新收费基数"
        result, _ = DATA.monitor(DATA.normalize(document([original, repost])), state, date(2026, 11, 25))
        self.assertEqual(result["changes"][0]["type"], "changed")

    def test_failed_first_run_retains_earliest_query_start(self):
        raw = document([self.tender()])
        raw["sources"].append({"source_id": "failed", "url": "https://example.org/failed", "status": "failed"})
        first, state = DATA.monitor(DATA.normalize(raw), {}, date(2026, 11, 25))
        second, state = DATA.monitor(DATA.normalize(raw), state, date(2026, 12, 10))
        self.assertFalse(first["coverage_complete_for_supplied_sources"])
        self.assertEqual(second["query_start"], "2026-11-18")
        self.assertNotIn("last_complete_date", state)

    def test_archived_sources_do_not_prove_complete_daily_search(self):
        raw = document([self.tender()])
        result, state = DATA.monitor(DATA.normalize(raw), {}, date(2026, 11, 25))
        self.assertFalse(result["coverage_complete_for_supplied_sources"])
        raw["coverage"].update(search_completed=True, query_start="2026-11-18", searched_through="2026-11-25")
        result, state = DATA.monitor(DATA.normalize(raw), state, date(2026, 11, 25))
        self.assertTrue(result["coverage_complete_for_supplied_sources"])
        self.assertEqual(state["last_complete_date"], "2026-11-25")
        self.assertNotIn("pending_query_start", state)

    def test_dry_run_does_not_mutate_state_and_cli_aliases_work(self):
        with tempfile.TemporaryDirectory(prefix="procurement-check-") as temporary:
            root = Path(temporary)
            source = root / "evidence.json"
            normal = root / "normalized.json"
            source.write_text(json.dumps(document([notice()]), ensure_ascii=False), encoding="utf-8")
            def run(*args):
                result = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stderr)
                return result
            run("normalize", "--input", str(source), "--output", str(normal))
            output = root / "statistics.json"
            run("stats", "--input", str(normal), "--output", str(output), "--from", "2026-10-01", "--to", "2026-10-31")
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["cohort"]["lot_count"], 1)
            state = root / "state.json"
            report = root / "daily.md"
            run("monitor", "--input", str(normal), "--state", str(state), "--output", str(report), "--as-of", "2026-11-25", "--dry-run")
            self.assertTrue(report.exists())
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
