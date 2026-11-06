from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


NOW = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)


def record() -> dict[str, object]:
    return {
        "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
        "submission_id": "SUB-D12-REPARSE-0001",
        "title": "D12 isolated reparse probe",
        "identity": {"platform": "COUPANG_TW", "product_id": "PROD-D12", "sku_id": "SKU-D12", "seller_id": "SELLER-D12", "condition": "NEW", "package_signature": "EACH-1", "currency": "TWD"},
        "observed_at": "2026-11-05T15:00:00+08:00",
        "quantity": 1,
        "before_coupon_price_twd": 100,
        "user_reported_coupon": {"status": "NONE", "price_twd": None, "eligibility": "UNKNOWN", "evidence_level": "NONE", "evidence_note": None, "valid_from": None, "valid_until": None},
        "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None},
        "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "D12 isolated local probe"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b15-root", type=Path, required=True)
    parser.add_argument("--nominal-project", type=Path, required=True)
    parser.add_argument("--outside-target", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    service = args.b15_root.resolve() / "services/private_observation_b15"
    sys.path.insert(0, str(service))
    from private_observation_b15.store import ObservationStore
    from private_observation_b15.validation import parse_and_validate

    nominal = args.nominal_project.resolve(strict=False)
    outside = args.outside_target.resolve(strict=True)
    requested_root = args.nominal_project.absolute() / "data/private_user_observations_b15"
    raw = json.dumps(record(), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    normalized = parse_and_validate(raw, now=NOW)
    store = ObservationStore(requested_root, clock=lambda: NOW)
    result = store.commit(normalized)
    actual_database = store.database.resolve(strict=True)
    nominal_lexical = args.nominal_project.absolute()
    escaped_nominal = not actual_database.is_relative_to(nominal_lexical)
    landed_outside = actual_database.is_relative_to(outside)
    connection = sqlite3.connect(actual_database)
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    connection.close()
    evidence = {
        "schema": "CDH-D12-B15-REPARSE-PROBE-1",
        "requested_data_root": "<D12_PROBE>/nominal_project/data/private_user_observations_b15",
        "resolved_store_root": "<D12_PROBE>/outside_target/private_user_observations_b15",
        "resolved_database": "<D12_PROBE>/outside_target/private_user_observations_b15/private_user_observations.sqlite3",
        "nominal_project": "<D12_PROBE>/nominal_project",
        "outside_target": "<D12_PROBE>/outside_target",
        "escaped_nominal_project": escaped_nominal,
        "landed_in_junction_target": landed_outside,
        "database_created": actual_database.is_file(),
        "database_sha256": hashlib.sha256(actual_database.read_bytes()).hexdigest(),
        "sqlite_integrity": integrity,
        "observation_count": count,
        "commit_result": {"idempotent_replay": result["idempotent_replay"], "backup_created": result["backup_created"]},
        "finding": "P1_ANCESTOR_REPARSE_PROJECT_ESCAPE" if escaped_nominal and landed_outside else "NOT_REPRODUCED",
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["finding"] != "NOT_REPRODUCED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
