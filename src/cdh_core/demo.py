from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from .models import HISTORY_TIMEZONE, BaselineSnapshot, MoneyValue, OfferIdentity, PurchaseScenario, StockState, ValueState
from .persistence import CurrentState, EventStore, MockSink
from .policy import PolicyContext, decide
from .pricing import PricingInput, calculate_total


def _money(case: dict[str, object], key: str) -> MoneyValue:
    state_key = f"{key}_state"
    if state_key in case:
        return MoneyValue.unavailable(ValueState(str(case[state_key])), evidence_id=f"demo:{key}")
    return MoneyValue.known(int(case[key]))


def run_demo(fixtures: Path, db_path: Path) -> dict[str, object]:
    document = json.loads(fixtures.read_text(encoding="utf-8"))
    now = datetime.fromisoformat(document["fake_now"])
    store = EventStore(db_path)
    sink = MockSink()
    results: list[dict[str, object]] = []

    for index, case in enumerate(document["cases"]):
        offer = OfferIdentity("TEST", case["id"], case["sku"], "seller-test", "NEW", "unit", "SYNTHETIC")
        scenario = PurchaseScenario(
            offer,
            case.get("context_id", "wow-test"),
            int(case["quantity"]),
            case.get("membership_context", "WOW_USER_DECLARED_TEST"),
            target_total_minor=case.get("target_total_minor"),
            eligibility_profile_version="demo-profile-v1",
            price_basis="CURRENT_TOTAL",
            purchase_channel="OFFLINE_TEST",
            payment_method="OFFLINE_TEST",
        )
        pricing = PricingInput(
            subtotal=_money(case, "subtotal_minor"),
            shipping=_money(case, "shipping_minor"),
            fees=(),
            tax=_money(case, "tax_minor"),
            minimum_quantity=int(case.get("minimum_quantity", 1)),
            independently_purchasable=bool(case.get("independently_purchasable", True)),
            requires_additional_items=bool(case.get("requires_additional_items", False)),
            evaluated_at=now,
            evidence_expires_at=now + timedelta(minutes=5),
            quote_evidence_id=f"demo-quote:{case['id']}",
        )
        cost = calculate_total(scenario, pricing)
        baseline = None
        if case.get("baseline_item_minor") is not None:
            baseline = BaselineSnapshot(
                int(case["baseline_item_minor"]),
                3,
                7,
                7,
                now - timedelta(days=1),
                True,
                "BASELINE_READY",
                event_time=now,
                series_key=scenario.history_series_key,
                scenario_scope=scenario.scope_key,
                offer_key=scenario.offer.key,
                context_id=scenario.context_id,
                membership_context=scenario.membership_context,
                eligibility_profile_version=scenario.eligibility_profile_version,
                coupon_plan_id=scenario.coupon_plan_id,
                quantity=scenario.quantity,
                price_basis=scenario.price_basis,
                contributing_observation_count=7,
                last_eligible_history_day=(now - timedelta(days=1)).astimezone(HISTORY_TIMEZONE).date().isoformat(),
            )
        context = PolicyContext.synthetic_verified(
            now,
            scenario,
            expires_at=now + timedelta(minutes=5),
            stock=StockState.IN_STOCK,
        )
        decision = decide(scenario, cost, baseline, context)
        result: dict[str, object] = {
            "id": case["id"],
            "expected_reason": case["expected_reason"],
            "decision_reason": decision.primary_reason,
            "notify": decision.notify,
            "total_minor": decision.total_minor,
            "cost_reasons": list(cost.reason_codes),
        }
        if decision.notify:
            state = CurrentState.verified_from(
                scenario,
                cost,
                now=now,
                expires_at=now + timedelta(minutes=5),
            )
            store.set_current_state(state, now=now)
            event_id, created = store.enqueue(
                scenario,
                decision,
                request_id=f"demo-{case['id']}",
                dedupe_key=f"demo-dedupe-{case['id']}",
                expected_fingerprint=cost.quote_fingerprint or "",
                expires_at=now + timedelta(minutes=5),
                now=now,
            )
            if case.get("supersede_before_delivery"):
                changed = replace(
                    state,
                    quote_fingerprint=f"{case['id']}:v2:raised",
                    semantic_fingerprint=f"{case['id']}:semantic:v2:raised",
                    total_minor=int(decision.total_minor) + 10_000,
                    observed_at=now + timedelta(seconds=30),
                    received_at=now + timedelta(seconds=30),
                )
                store.set_current_state(changed, now=now + timedelta(seconds=30))
            result["event_id"] = event_id
            result["event_created"] = created
            result["delivery_status"] = store.deliver(event_id, sink, now=now + timedelta(minutes=1))
        results.append(result)

    passed = all(row["decision_reason"] == row["expected_reason"] for row in results)
    return {
        "product_mode": "OFFLINE_ONLY",
        "fixture": str(fixtures),
        "fake_now": document["fake_now"],
        "all_expected_reasons_match": passed,
        "results": results,
        "mock_delivery_count": len(sink.deliveries),
        "database_counts": store.counts(),
        "schema_version": store.schema_version(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="CDH C01 synthetic offline demo")
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_demo(args.fixtures, args.db)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not result["all_expected_reasons_match"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

