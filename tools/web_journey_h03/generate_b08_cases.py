from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
BACKEND = "B09" if "--backend=B09" in sys.argv else "B08"
PACKAGE = "CDH_B09_001_REVIEW" if BACKEND == "B09" else "CDH_B08_001_REVIEW"
BACKEND_ROOT = PROJECT / "review" / "H03" / "baselines" / BACKEND / PACKAGE
ADAPTER = BACKEND_ROOT / "services" / "price_quality_adapter"
SCHEMA = (ADAPTER / "SCHEMA.sql").read_text(encoding="utf-8")
RUNTIME = PROJECT / "review" / "H03" / "runtime"
FIXTURES = RUNTIME / "fixtures"
OUTPUT = RUNTIME / f"{BACKEND}_CASES.json"
NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)

sys.path.insert(0, str(ADAPTER))
from price_quality_adapter import PriceQualityRepository  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_text(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def observation(case: str, index: int, when: datetime, price: int) -> dict[str, object]:
    return {
        "series_key": case,
        "submission_id": f"{case}-{index}",
        "observed_at_utc": utc_text(when),
        "taipei_date": (when + timedelta(hours=8)).date().isoformat(),
        "price_twd": price,
        "source_type": "SYNTHETIC",
        "source_id": f"h03-{case}-{index}",
        "data_classification": "SYNTHETIC_FIXTURE",
        "is_synthetic": 1,
    }


def series(case: str, *, incomplete: bool = False) -> dict[str, object]:
    return {
        "series_key": case,
        "title": f"TEST_ONLY H03 {case}",
        "platform": "COUPANG_TW",
        "product_id": f"product-{case}",
        "seller_id": None if incomplete else f"seller-{case}",
        "variant_id": f"sku-{case}",
        "spec_signature": "test_only=1;size=100g",
        "minimum_purchase_quantity": 1,
        "package_signature": "1x100g",
        "item_condition": "NEW",
        "price_basis": "CURRENT_ITEM_PRICE",
        "identity_state": "INCOMPLETE" if incomplete else "EXACT",
        "exact_match_claim_allowed": 0 if incomplete else 1,
        "shipping_status": "UNKNOWN",
        "data_classification": "SYNTHETIC_FIXTURE",
        "source_kind": "SYNTHETIC",
        "quality_flags_json": "[]",
    }


def create_repository(root: Path, row: dict[str, object], observations: list[dict[str, object]]) -> PriceQualityRepository:
    root.mkdir(parents=True, exist_ok=False)
    database = root / "snapshot.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(SCHEMA)
    connection.execute("INSERT INTO adapter_schema VALUES(1)")
    connection.execute(
        "INSERT INTO snapshot_metadata VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            f"h03-{row['series_key']}",
            "CDH-PRICE-QUALITY-READMODEL-1",
            "CDH-WEB-CONTRACT-V2",
            "SYNTHETIC_FIXTURE",
            "ACTIVE_SYNTHETIC_FIXTURE",
            "2026-11-05T00:00:00Z",
            "2027-01-01T00:00:00Z",
            None,
            "1" * 64,
            "2" * 64,
        ),
    )
    connection.execute(
        "INSERT INTO series VALUES(:series_key,:title,:platform,:product_id,:seller_id,:variant_id,:spec_signature,"
        ":minimum_purchase_quantity,:package_signature,:item_condition,:price_basis,:identity_state,"
        ":exact_match_claim_allowed,:shipping_status,:data_classification,:source_kind,:quality_flags_json)",
        row,
    )
    for index, item in enumerate(observations, 1):
        connection.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                index,
                item["series_key"],
                item["submission_id"],
                item["observed_at_utc"],
                item["taipei_date"],
                item["price_twd"],
                item["source_type"],
                item["source_id"],
                item["data_classification"],
                item["is_synthetic"],
            ),
        )
    connection.commit()
    connection.close()
    authority = root / "snapshot.authority.json"
    authority.write_text(
        json.dumps(
            {
                "schema_version": "CDH-B08-SNAPSHOT-AUTHORITY-1",
                "database_sha256": sha256(database),
                "data_classification": "SYNTHETIC_FIXTURE",
                "contains_private_data": False,
                "authorized_use": "OFFLINE_LOCAL_READONLY_B08_ONLY",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return PriceQualityRepository(database, authority_file=authority, allowed_root=root, clock=lambda: NOW)


def main() -> None:
    if FIXTURES.exists():
        shutil.rmtree(FIXTURES)
    FIXTURES.mkdir(parents=True)
    cases: list[dict[str, object]] = []
    specifications = [
        (
            "valid",
            series("valid"),
            [
                observation("valid", 1, NOW - timedelta(days=3, hours=2), 30),
                observation("valid", 2, NOW - timedelta(days=2, hours=2), 20),
                observation("valid", 3, NOW - timedelta(days=1, hours=2), 10),
            ],
        ),
        (
            "unavailable",
            series("unavailable", incomplete=True),
            [observation("unavailable", 1, NOW - timedelta(days=1, hours=2), 77)],
        ),
        (
            "raw_min_mismatch",
            series("raw_min_mismatch"),
            [
                observation("raw_min_mismatch", 1, NOW - timedelta(days=2, hours=3), 10),
                observation("raw_min_mismatch", 2, NOW - timedelta(days=2, hours=2), 20),
                observation("raw_min_mismatch", 3, NOW - timedelta(days=2, hours=1), 30),
            ],
        ),
    ]
    for name, row, observations in specifications:
        repository = create_repository(FIXTURES / name, row, observations)
        key = str(row["series_key"])
        search = repository.search("", page=1, limit=100)
        detail = repository.detail(key)
        quality = repository.quality(key)
        affiliate = repository.affiliate(key)
        assert detail is not None and quality is not None and affiliate is not None
        cases.append(
            {
                "case": name,
                "test_only": True,
                "source": f"EXACT_{BACKEND}_PRICE_QUALITY_REPOSITORY",
                "search": search,
                "detail": detail,
                "affiliate": affiliate,
                "quality": quality,
                "derived": {
                    "raw_history_min_twd": min((point["price_twd"] for point in detail["history"]), default=None),
                    "v2_observation_period_min_twd": detail["observation_period_min_twd"],
                    "v3_daily_period_low_twd": quality["period_low_twd"],
                },
            }
        )
    output = {
        "task_id": "CDH-H03-A07-B08-INTEGRATION-JOURNEY-001",
        "authority": "AUTHORIZED_SYNTHETIC_OFFLINE_ONLY",
        "clock_utc": utc_text(NOW),
        "backend": BACKEND,
        "backend_repository": str(BACKEND_ROOT.relative_to(PROJECT)).replace("\\", "/"),
        "cases": cases,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(OUTPUT), "cases": len(cases)}))


if __name__ == "__main__":
    main()
