from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cdh_core.models import POLICY_VERSION
from cdh_integration.adapter import QualificationFixture, SyntheticObservation


NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def observation(sku: str, price_minor: int) -> dict[str, object]:
    return {
        "source_class": "SYNTHETIC_TEST_PAGE",
        "sku": sku,
        "product_url": f"https://synthetic.invalid/products/{sku.lower()}",
        "price_minor": price_minor,
        "currency": "TWD",
        "observed_at": iso(NOW - timedelta(minutes=1)),
        "title": f"I01 synthetic fixture {sku}",
    }


def qualification(
    raw: dict[str, object],
    *,
    shipping_minor: int = 0,
    target_total_minor: int | None = None,
    history_unit_minor: int | None = None,
) -> dict[str, object]:
    parsed = SyntheticObservation.parse(raw)
    seller_id = "SYNTH-SELLER-CLI"
    package_signature = "SYNTH-PACK-CLI"
    history = []
    if history_unit_minor is not None:
        history = [
            {"observed_at": iso(NOW - timedelta(days=day, hours=1)), "unit_minor": history_unit_minor}
            for day in range(1, 8)
        ]
    return {
        "fixture_class": "SYNTHETIC_QUALIFICATION_FIXTURE",
        "fixture_id": f"FIXTURE-{parsed.sku}",
        "source_payload_sha256": parsed.source_payload_sha256,
        "sku": parsed.sku,
        "product_url": parsed.product_url,
        "seller_id": seller_id,
        "condition": "NEW_SYNTHETIC",
        "package_signature": package_signature,
        "delivery_type": "SYNTHETIC_DELIVERY",
        "price_minor": parsed.price_minor,
        "price_scenario_id": QualificationFixture.expected_price_scenario_id(
            parsed,
            seller_id=seller_id,
            package_signature=package_signature,
            quantity=1,
        ),
        "observation_observed_at": iso(parsed.observed_at),
        "context_id": "I01-SYNTHETIC-CLI",
        "membership_context": "WOW_SYNTHETIC",
        "eligibility_profile_version": "ELIGIBILITY-SYNTH-v1",
        "policy_version": POLICY_VERSION,
        "source_permission_version": "OFFLINE-SYNTHETIC-v1",
        "fixture_observed_at": iso(parsed.observed_at - timedelta(minutes=1)),
        "fixture_expires_at": iso(NOW + timedelta(minutes=10)),
        "quantity": 1,
        "minimum_quantity": 1,
        "stock_state": "IN_STOCK",
        "eligibility_state": "ELIGIBLE",
        "independently_purchasable": True,
        "requires_additional_items": False,
        "shipping_minor": shipping_minor,
        "fees": [],
        "tax_minor": 0,
        "subscription_or_deposit": False,
        "user_enabled": True,
        "notifications_enabled": True,
        "source_allowed": True,
        "coupon_plan_id": None,
        "coupon": None,
        "target_total_minor": target_total_minor,
        "purchase_channel": "WEB_SYNTHETIC",
        "payment_method": "NONE_SYNTHETIC",
        "availability_version": "availability-v1",
        "history": history,
        "price_basis": "TOTAL_FOR_QUANTITY",
        "quoted_quantity": 1,
        "total_quote_evidence_id": f"I01-CLI-QUOTE-{parsed.sku}",
    }


def main() -> int:
    zero_unknown = observation("SYNTH-I01-CLI-000", 0)
    zero_qualified = observation("SYNTH-I01-CLI-001", 0)
    normal_five = observation("SYNTH-I01-CLI-002", 500)
    target_five = observation("SYNTH-I01-CLI-003", 500)
    paid_o2 = observation("SYNTH-I01-CLI-004", 5_000)
    cases = [
        {"case_id": "ZERO_SHIPPING_UNKNOWN", "observation": zero_unknown},
        {
            "case_id": "ZERO_FULLY_QUALIFIED",
            "observation": zero_qualified,
            "qualification_fixture": qualification(zero_qualified),
            "deliver": True,
        },
        {
            "case_id": "NORMAL_FIVE_NOT_DEAL",
            "observation": normal_five,
            "qualification_fixture": qualification(normal_five, history_unit_minor=500),
        },
        {
            "case_id": "TARGET_FIVE",
            "observation": target_five,
            "qualification_fixture": qualification(target_five, target_total_minor=500, history_unit_minor=500),
            "deliver": True,
        },
        {
            "case_id": "PAID_SHIPPING_O2",
            "observation": paid_o2,
            "qualification_fixture": qualification(paid_o2, shipping_minor=6_000, history_unit_minor=100_000),
            "deliver": True,
        },
    ]
    output = Path("fixtures/i01/synthetic_integration_cases.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": output.as_posix(), "case_count": len(cases)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
