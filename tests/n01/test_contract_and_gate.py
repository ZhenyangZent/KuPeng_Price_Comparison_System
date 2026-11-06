from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

from cdh_core.models import Decision

from n01_alerts.contracts import (
    REAL_DELIVERY_ENABLED,
    TELEGRAM_INTERFACE,
    WINDOWS_TOAST_INTERFACE,
    candidate_from_c01,
    candidate_from_i01,
)
from n01_alerts.models import free_shipping_gate
from n01_alerts.sinks import RealDeliveryDisabled, TelegramSinkInterface, WindowsToastSinkInterface

from tests.n01.helpers import NOW, approved_c01_candidate, candidate, state


class ContractTests(unittest.TestCase):
    def test_c01_approved_decision_converts(self) -> None:
        _, _, item = approved_c01_candidate()
        self.assertEqual((item.source_kind, item.source_status), ("SYNTHETIC", "SOURCE_BLOCKED"))
        self.assertTrue(item.decision_notify)

    def test_tampered_c01_decision_is_rejected(self) -> None:
        scenario, decision, _ = approved_c01_candidate()
        bad = replace(decision, total_minor=0)
        with self.assertRaisesRegex(ValueError, "C01_DECISION_APPROVAL_INVALID"):
            candidate_from_c01(
                scenario,
                bad,
                request_id="bad",
                user_policy_scope=scenario.user_policy_scope_key,
                sku_id="sku-1",
                minimum_quantity=1,
                policy_epoch=1,
                source_revision=1,
                subtotal_minor=0,
                shipping_minor=0,
                fees_minor=0,
                tax_minor=0,
                coupon_discount_minor=0,
                coupon_expires_at=None,
                stock="IN_STOCK",
                notifications_enabled=True,
                user_enabled=True,
                baseline_reliable=False,
                cost_semantic_fingerprint="bad",
            )

    def test_i01_queued_result_shape_converts(self) -> None:
        scenario, decision, _ = approved_c01_candidate()
        result = SimpleNamespace(status="QUEUED", scenario=scenario, decision=decision)
        item = candidate_from_i01(
            result,
            request_id="i01-shape",
            user_policy_scope=scenario.user_policy_scope_key,
            sku_id="sku-1",
            minimum_quantity=1,
            policy_epoch=1,
            source_revision=1,
            subtotal_minor=500,
            shipping_minor=0,
            fees_minor=0,
            tax_minor=0,
            coupon_discount_minor=0,
            coupon_expires_at=None,
            stock="IN_STOCK",
            notifications_enabled=True,
            user_enabled=True,
            baseline_reliable=False,
            cost_semantic_fingerprint="cost-semantic-c01",
        )
        self.assertEqual(item.total_minor, 500)

    def test_i01_nonqueued_result_is_rejected(self) -> None:
        scenario, decision, _ = approved_c01_candidate()
        with self.assertRaisesRegex(ValueError, "I01_RESULT_NOT_QUEUED"):
            candidate_from_i01(SimpleNamespace(status="FILTERED", scenario=scenario, decision=decision))

    def test_real_channel_interfaces_are_disabled(self) -> None:
        self.assertFalse(REAL_DELIVERY_ENABLED)
        self.assertFalse(WINDOWS_TOAST_INTERFACE["enabled"])
        self.assertFalse(TELEGRAM_INTERFACE["enabled"])
        with self.assertRaises(RealDeliveryDisabled):
            WindowsToastSinkInterface().deliver("e", {})
        with self.assertRaises(RealDeliveryDisabled):
            TelegramSinkInterface().deliver("e", {})


class FreeShippingGateTests(unittest.TestCase):
    def assertAllowed(self, item):
        result = free_shipping_gate(item, state(item), NOW + timedelta(minutes=1))
        self.assertTrue(result.allowed, result.reasons)
        return result

    def assertBlocked(self, item, latest, reason):
        result = free_shipping_gate(item, latest, NOW + timedelta(minutes=1))
        self.assertFalse(result.allowed)
        self.assertIn(reason, result.reasons)

    def test_zero_one_and_nine_free_shipping_pass(self) -> None:
        for index, value in enumerate((0, 100, 900)):
            with self.subTest(value=value):
                item = candidate(
                    request_id=f"p-{index}",
                    total_minor=value,
                    subtotal_minor=value,
                    decision_reason="S0" if value == 0 else "S1",
                )
                self.assertAllowed(item)

    def test_paid_shipping_without_exception_blocks(self) -> None:
        item = candidate(total_minor=600, subtotal_minor=500, shipping_minor=100)
        self.assertBlocked(item, state(item), "NO_FREE_SHIPPING_POLICY_MATCH")

    def test_paid_shipping_o1_o2_reliable_total_pass(self) -> None:
        for reason in ("O1", "O2"):
            item = candidate(
                request_id=reason,
                total_minor=600,
                subtotal_minor=500,
                shipping_minor=100,
                decision_reason=reason,
                baseline_total_minor=1000,
                baseline_reliable=True,
            )
            self.assertAllowed(item)

    def test_refund_points_fake_zero_blocks(self) -> None:
        item = candidate(total_minor=0, subtotal_minor=0, decision_reason="S0", zero_total_provenance="REFUND_POINTS")
        self.assertBlocked(item, state(item), "ZERO_TOTAL_PROVENANCE_INVALID")

    def test_minimum_quantity_blocks(self) -> None:
        item = candidate(quantity=1, minimum_quantity=2)
        self.assertBlocked(item, state(item), "MINIMUM_QUANTITY_NOT_MET")

    def test_unknown_shipping_coupon_or_fee_blocks(self) -> None:
        for field_name in ("shipping_minor", "fees_minor", "coupon_discount_minor"):
            item = candidate(**{field_name: None})
            self.assertBlocked(item, state(item), f"{field_name.upper()}_UNKNOWN")

    def test_expired_coupon_blocks(self) -> None:
        item = candidate(
            total_minor=400,
            subtotal_minor=500,
            coupon_discount_minor=100,
            coupon_expires_at=NOW + timedelta(seconds=30),
        )
        self.assertBlocked(item, state(item), "COUPON_EXPIRED")

    def test_membership_policy_sku_quantity_and_source_revision_changes_block(self) -> None:
        item = candidate()
        cases = (
            (state(item, membership_context="NON_WOW"), "MEMBERSHIP_CHANGED"),
            (state(item, policy_epoch=2), "POLICY_EPOCH_CHANGED"),
            (state(item, sku_id="sku-2"), "SKU_CHANGED"),
            (state(item, quantity=2), "QUANTITY_CHANGED"),
            (state(item, source_revision=2), "SOURCE_REVISION_CHANGED"),
        )
        for latest, reason in cases:
            with self.subTest(reason=reason):
                self.assertBlocked(item, latest, reason)

    def test_expiry_disable_stock_and_offline_block(self) -> None:
        item = candidate(expires_at=NOW + timedelta(seconds=30))
        self.assertFalse(free_shipping_gate(item, state(item), NOW + timedelta(minutes=1)).allowed)
        base = candidate()
        for latest, reason in (
            (state(base, notifications_enabled=False), "NOTIFICATIONS_DISABLED"),
            (state(base, stock="OUT_OF_STOCK"), "NOT_IN_STOCK"),
            (state(base, source_available=False), "SOURCE_OFFLINE"),
        ):
            self.assertBlocked(base, latest, reason)

    def test_target_and_true_discount_are_separate_from_low_price(self) -> None:
        target = candidate(decision_reason="TARGET_REACHED")
        self.assertEqual(self.assertAllowed(target).display_category, "TARGET_PRICE_REACHED")
        ordinary_five = candidate(total_minor=500, subtotal_minor=500, decision_reason="S1")
        self.assertEqual(self.assertAllowed(ordinary_five).display_category, "LOW_ABSOLUTE_PRICE")
        discount = candidate(
            total_minor=500,
            subtotal_minor=500,
            baseline_total_minor=900,
            baseline_reliable=True,
        )
        self.assertEqual(self.assertAllowed(discount).display_category, "VERIFIED_DISCOUNT")


if __name__ == "__main__":
    unittest.main()
