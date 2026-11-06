from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "apps" / "n01"), str(ROOT / "src")]

from n01_alerts.models import LatestState, NotificationCandidate  # noqa: E402
from n01_alerts.service import NotificationService  # noqa: E402
from n01_alerts.sinks import MockSink  # noqa: E402


def main() -> int:
    sample_root = ROOT / "experiments" / "N01" / "sample_generation"
    if sample_root.exists():
        shutil.rmtree(sample_root)
    sample_root.mkdir(parents=True)
    now = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    candidate = NotificationCandidate(
        request_id="sample-request-1",
        scenario_scope="sample-scenario",
        user_policy_scope="sample-user-policy",
        offer_key="sample-offer",
        sku_id="sample-sku",
        quantity=1,
        minimum_quantity=1,
        membership_context="WOW",
        eligibility_profile_version="sample-profile-v1",
        policy_epoch=1,
        source_revision=1,
        source_kind="SYNTHETIC",
        source_status="SOURCE_BLOCKED",
        observed_at=now,
        expires_at=now + timedelta(days=1),
        decision_fingerprint="sample-decision-fingerprint",
        policy_evidence_fingerprint="sample-policy-evidence-fingerprint",
        decision_reason="TARGET_REACHED",
        decision_labels=("FREE_SHIPPING", "TARGET"),
        decision_notify=True,
        total_minor=900,
        subtotal_minor=900,
        shipping_minor=0,
        fees_minor=0,
        tax_minor=0,
        coupon_discount_minor=0,
        coupon_expires_at=None,
        stock="IN_STOCK",
        notifications_enabled=True,
        user_enabled=True,
        target_total_minor=900,
        baseline_total_minor=1200,
        baseline_reliable=True,
        cost_semantic_fingerprint="sample-cost-semantic",
        zero_total_provenance="VERIFIED_PURCHASE_TOTAL",
    )
    service = NotificationService(sample_root / "outbox.sqlite3")
    submitted = service.submit(candidate, LatestState.from_candidate(candidate), now=now + timedelta(minutes=1))
    delivered = service.dispatch_one(MockSink(), worker_id="sample-worker", now=now + timedelta(minutes=2))
    digest = service.daily_digest(
        now.astimezone(ZoneInfo("Asia/Taipei")).date(),
        now=now + timedelta(minutes=3),
    )
    digest["sample_execution"] = {"submit_status": submitted.status, "dispatch_status": delivered.status}
    reports = ROOT / "reports" / "N01"
    (reports / "DAILY_DIGEST_SAMPLE.json").write_text(
        json.dumps(digest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (reports / "OBSERVABILITY_SAMPLE.json").write_text(
        json.dumps(service.stats(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"digest_items": len(digest["items"]), "stats": service.stats()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
