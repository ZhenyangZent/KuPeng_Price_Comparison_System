from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "input" / "specification" / "Coupang_Deal_Hunter_V3.0" / "Coupang_Deal_Hunter_V3.0_Full_Plan.md"
OUTPUT = ROOT / "reports" / "REQUIREMENT_TRACEABILITY.csv"

PASS_EVIDENCE = {
    "T01": "test_history_policy.PolicyTests.test_s0_zero_total_free_shipping",
    "T02": "test_history_policy.PolicyTests.test_zero_product_plus_shipping_without_baseline_is_silent",
    "T03": "test_history_policy.PolicyTests.test_eligibility_unknown_ineligible_and_conflict_are_distinct",
    "T04": "test_models_pricing.MoneyModelTests.test_bool_float_nan_infinity_and_null_rejected",
    "T06": "test_rework_regressions.PropertyAndBindingTests.test_coupon_threshold_requires_separate_no_coupon_scenario",
    "T08": "test_rework_regressions.AuditCounterexampleRegressionTests.test_aud_05_semantic_dedupe_ignores_caller_key_variation",
    "T11": "test_models_pricing.PricingTests.test_additional_item_bundle_blocks",
    "T14": "test_history_policy.PolicyTests.test_out_of_stock_and_subscription_fail_closed",
    "T15": "test_rework_regressions.AuditCounterexampleRegressionTests.test_aud_03_unbound_cross_sku_baseline_cannot_authorize_o2",
    "T18": "test_models_pricing.PricingTests.test_unknown_shipping_blocks",
    "T19": "test_models_pricing.PricingTests.test_expired_coupon_is_not_applied",
    "T21": "test_history_policy.HistoryTests.test_m30_requires_seven_valid_days",
    "T22": "test_history_policy.HistoryTests.test_first_observation_is_not_new_low",
    "T23": "test_history_policy.HistoryTests.test_same_utc_hour_only_first_affects_daily_median",
    "T31": "test_persistence_demo.PersistenceTests.test_injected_transaction_failure_rolls_back_both",
    "T32": "test_persistence_demo.PersistenceTests.test_concurrent_enqueue_creates_one_event",
    "T35": "test_persistence_demo.PersistenceTests.test_ambiguous_and_failed_delivery_are_distinct",
    "T37": "test_history_policy.PolicyTests.test_each_hard_gate_fails_closed",
    "T39": "test_rework_regressions.AuditCounterexampleRegressionTests.test_aud_01_membership_is_part_of_evidence_scope; test_persistence_demo.PersistenceTests.test_stock_membership_source_and_notification_changes_supersede",
    "T41": "test_history_policy.PolicyTests.test_s1_without_history_is_candidate; test_history_policy.PolicyTests.test_paid_shipping_target_does_not_bypass_exception",
    "T42": "test_history_policy.PolicyTests.test_o2",
    "T43": "test_history_policy.PolicyTests.test_o1",
    "T44": "test_history_policy.PolicyTests.test_q2_exact_s3_example",
    "T45": "test_models_pricing.PricingTests.test_unknown_tax_blocks_even_with_free_shipping",
    "T47": "test_models_pricing.PricingTests.test_additional_item_bundle_blocks",
    "T48": "test_history_policy.PolicyTests.test_zero_product_plus_shipping_without_baseline_is_silent",
    "T49": "test_history_policy.PolicyTests.test_minimum_100_one_dollar_each_not_s1",
    "T50": "test_history_policy.PolicyTests.test_four_dollar_two_units_is_s1",
    "T51": "test_models_pricing.PricingTests.test_coupon_not_double_deducted",
    "T52": "test_models_pricing.PricingTests.test_oversized_coupon_without_cap_rule_blocks",
    "T53": "test_history_policy.PolicyTests.test_zero_product_with_required_service_fee_is_not_s0",
    "T54": "test_models_pricing.PricingTests.test_included_tax_not_added_again",
    "T55": "test_history_policy.PolicyTests.test_zero_baseline_does_not_divide",
    "T56": "test_history_policy.HistoryTests.test_taipei_current_day_excluded_from_own_baseline",
    "T58": "test_models_pricing.PricingTests.test_coupon_unknown_eligibility_blocks_coupon_scenario",
    "T59": "test_rework_regressions.AuditCounterexampleRegressionTests.test_aud_09_app_and_payment_coupon_requires_matching_context",
    "T62": "test_rework_regressions.PersistenceHardeningTests.test_severity_flicker_with_same_verified_price_is_deduplicated",
    "T64": "test_models_pricing.PricingTests.test_unknown_tax_blocks_even_with_free_shipping",
    "T68": "test_persistence_demo.PersistenceTests.test_restart_preserves_deduplication; test_rework_regressions.AuditCounterexampleRegressionTests.test_aud_06_divergent_request_id_reuse_is_conflict",
    "T74": "test_rework_regressions.PersistenceHardeningTests.test_same_semantic_state_after_24_hours_does_not_force_resend",
    "T75": "test_history_policy.PolicyTests.test_o2",
    "T76": "test_models_pricing.MoneyModelTests.test_bool_float_nan_infinity_and_null_rejected",
    "T80": "test_persistence_demo.PersistenceTests.test_stock_membership_source_and_notification_changes_supersede",
    "T81": "test_history_policy.PolicyTests.test_target_reached_at_twenty_percent_drop",
    "T82": "test_history_policy.PolicyTests.test_target_without_history",
    "T83": "test_history_policy.PolicyTests.test_paid_shipping_target_does_not_bypass_exception",
    "T84": "test_history_policy.PolicyTests.test_same_five_dollar_baseline_is_not_sale",
    "T85": "test_history_policy.PolicyTests.test_s1_without_history_is_candidate",
    "T86": "test_history_policy.HistoryTests.test_latest_older_than_seven_days_is_stale",
    "T87": "test_models_pricing.EvidenceScopeTests.test_different_context_is_rejected; test_rework_regressions.AuditCounterexampleRegressionTests.test_aud_01_membership_is_part_of_evidence_scope; test_rework_regressions.AuditCounterexampleRegressionTests.test_aud_03_unbound_cross_sku_baseline_cannot_authorize_o2",
    "T88": "test_persistence_demo.PersistenceTests.test_price_raise_supersedes_queued_event",
    "T89": "test_persistence_demo.PersistenceTests.test_stock_membership_source_and_notification_changes_supersede",
    "T90": "test_history_policy.PolicyTests.test_out_of_stock_and_subscription_fail_closed",
    "T100": "test_persistence_demo.PersistenceTests.test_stock_membership_source_and_notification_changes_supersede",
    "T105": "test_persistence_demo.PersistenceTests.test_expired_event_not_delivered",
    "T106": "test_history_policy.PolicyTests.test_nine_point_zero_one_display_rounding_does_not_become_s1; test_rework_regressions.PropertyAndBindingTests.test_property_price_string_or_rounding_cannot_turn_901_into_900",
    "T107": "test_history_policy.PolicyTests.test_o1_exact_boundary_and_fraction_guard",
    "T108": "test_models_pricing.MoneyModelTests.test_boolean_quantity_rejected; test_models_pricing.MoneyModelTests.test_bool_float_nan_infinity_and_null_rejected",
    "T109": "test_rework_regressions.PropertyAndBindingTests.test_property_raising_known_cost_does_not_create_a_new_free_shipping_alert",
}

NOT_IN_SCOPE = {
    "T09", "T10", "T12", "T24", "T25", "T26", "T27", "T28", "T29", "T30",
    "T33", "T34", "T36", "T40", "T65", "T66", "T67", "T69", "T70", "T71",
    "T72", "T73", "T77", "T78", "T79", "T93", "T94", "T95", "T96", "T98",
    "T99", "T101", "T102", "T103", "T104", "T110", "T111", "T112",
}


def main() -> None:
    rows: list[dict[str, str]] = []
    pattern = re.compile(r"^\| (T\d{2,3}) \| (.*?) \| (.*?) \|$")
    for line in SPEC.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        test_id, scenario, expected = match.groups()
        if test_id in PASS_EVIDENCE:
            status = "PASS"
            evidence = PASS_EVIDENCE[test_id]
            note = "C01 R01 product/regression test executed; see the final raw test log."
        elif test_id in NOT_IN_SCOPE:
            status = "NOT_IN_SCOPE"
            evidence = "N/A"
            note = "Outside CDH-C01-REWORK-002; no browser, live source, GUI, native bridge, installer, or real notification work authorized."
        else:
            status = "NOT_EXECUTED"
            evidence = "NOT_RUN"
            note = "No exact product-level evidence in C01; excluded from PASS numerator."
        rows.append(
            {
                "TEST_ID": test_id,
                "SPEC_SECTION": "V3.0 §15",
                "SCENARIO": scenario,
                "EXPECTED_RESULT": expected,
                "C01_STATUS": status,
                "EVIDENCE": evidence,
                "NOTE": note,
            }
        )
    ids = [row["TEST_ID"] for row in rows]
    expected_ids = [f"T{i:02d}" if i < 100 else f"T{i}" for i in range(1, 113)]
    if ids != expected_ids:
        raise SystemExit(f"Traceability extraction mismatch: got {len(ids)} rows")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["C01_STATUS"]] = counts.get(row["C01_STATUS"], 0) + 1
    print(f"TRACEABILITY_ROWS={len(rows)}")
    for status in sorted(counts):
        print(f"{status}={counts[status]}")


if __name__ == "__main__":
    main()

