from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .targets import read_unique_member, unique_member_name


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)


def _backend_class(backend_zip: Path):
    member = unique_member_name(backend_zip, "services/price_quality_adapter/price_quality_adapter/__init__.py")
    internal = member[: -len("price_quality_adapter/__init__.py")].rstrip("/")
    import_path = str(backend_zip.resolve()) + "/" + internal
    for name in tuple(sys.modules):
        if name == "price_quality_adapter" or name.startswith("price_quality_adapter."):
            del sys.modules[name]
    sys.path[:] = [
        item for item in sys.path
        if not (".zip/" in item.replace("\\", "/") and item.replace("\\", "/").endswith("/services/price_quality_adapter"))
    ]
    if import_path not in sys.path:
        sys.path.insert(0, import_path)
    importlib.invalidate_caches()
    module = importlib.import_module("price_quality_adapter")
    return module.PriceQualityRepository


def _series(
    key: str,
    *,
    product: str = "product-1",
    seller: str | None = "seller-1",
    variant: str | None = "sku-1",
    identity: str = "EXACT",
    exact: int = 1,
    price_basis: str = "CURRENT_ITEM_PRICE",
) -> dict[str, object]:
    return {
        "series_key": key,
        "title": "Synthetic contract item",
        "platform": "COUPANG_TW",
        "product_id": product,
        "seller_id": seller,
        "variant_id": variant,
        "spec_signature": "size=1",
        "minimum_purchase_quantity": 1,
        "package_signature": "1x",
        "item_condition": "NEW" if exact else "UNKNOWN",
        "price_basis": price_basis,
        "identity_state": identity,
        "exact_match_claim_allowed": exact,
        "shipping_status": "UNKNOWN",
        "data_classification": "SYNTHETIC_FIXTURE",
        "source_kind": "SYNTHETIC",
        "quality_flags_json": "[]",
    }


def _observation(key: str, submission: str, when: datetime, price: int) -> dict[str, object]:
    return {
        "series_key": key,
        "submission_id": submission,
        "observed_at_utc": when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "taipei_date": (when.astimezone(timezone.utc) + timedelta(hours=8)).date().isoformat(),
        "price_twd": price,
        "source_type": "SYNTHETIC",
        "source_id": f"source-{submission}",
        "data_classification": "SYNTHETIC_FIXTURE",
        "is_synthetic": 1,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_repository(
    root: Path,
    backend_zip: Path,
    *,
    series: list[dict[str, object]],
    observations: list[dict[str, object]],
    permission: str = "ACTIVE_SYNTHETIC_FIXTURE",
    expires: str | None = "2027-01-01T00:00:00Z",
):
    root.mkdir(parents=True, exist_ok=False)
    database = root / "snapshot.sqlite3"
    schema = read_unique_member(backend_zip, "services/price_quality_adapter/SCHEMA.sql").decode("utf-8-sig")
    connection = sqlite3.connect(database)
    connection.executescript(schema)
    connection.execute("INSERT INTO adapter_schema VALUES(1)")
    connection.execute(
        "INSERT INTO snapshot_metadata VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("d06-snapshot", "CDH-PRICE-QUALITY-READMODEL-1", "CDH-WEB-CONTRACT-V2", "SYNTHETIC_FIXTURE", permission,
         "2026-11-01T00:00:00Z", expires, None, "1" * 64, "2" * 64),
    )
    for item in series:
        connection.execute(
            "INSERT INTO series VALUES(:series_key,:title,:platform,:product_id,:seller_id,:variant_id,:spec_signature,"
            ":minimum_purchase_quantity,:package_signature,:item_condition,:price_basis,:identity_state,"
            ":exact_match_claim_allowed,:shipping_status,:data_classification,:source_kind,:quality_flags_json)", item,
        )
    for index, item in enumerate(observations, 1):
        connection.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",
            (index, item["series_key"], item["submission_id"], item["observed_at_utc"], item["taipei_date"],
             item["price_twd"], item["source_type"], item["source_id"], item["data_classification"], item["is_synthetic"]),
        )
    connection.commit()
    connection.close()
    authority = root / "snapshot.authority.json"
    authority.write_text(json.dumps({
        "schema_version": "CDH-B08-SNAPSHOT-AUTHORITY-1",
        "database_sha256": _sha256(database),
        "data_classification": "SYNTHETIC_FIXTURE",
        "contains_private_data": False,
        "authorized_use": "OFFLINE_LOCAL_READONLY_B08_ONLY",
    }, sort_keys=True), encoding="utf-8")
    repository = _backend_class(backend_zip)
    return repository(database, authority_file=authority, allowed_root=root, clock=lambda: NOW)


def build_backend_evidence(root: Path, backend_zip: str | Path) -> dict[str, object]:
    target = Path(backend_zip)
    valid = make_repository(
        root / "valid", target,
        series=[_series("valid")],
        observations=[_observation("valid", "valid-1", NOW - timedelta(days=2), 100)],
    )
    incomplete = make_repository(
        root / "incomplete", target,
        series=[_series("incomplete", seller=None, variant=None, identity="INCOMPLETE", exact=0)],
        observations=[_observation("incomplete", "incomplete-1", NOW - timedelta(days=2), 50)],
    )
    daily_rows = [
        _observation("daily-median", "daily-10", datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc), 10),
        _observation("daily-median", "daily-20", datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc), 20),
        _observation("daily-median", "daily-30", datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc), 30),
    ]
    daily = make_repository(root / "daily", target, series=[_series("daily-median")], observations=daily_rows)
    zero = make_repository(
        root / "zero", target,
        series=[_series("zero")], observations=[_observation("zero", "zero-1", NOW - timedelta(days=2), 0)],
    )
    stale = make_repository(
        root / "stale", target,
        series=[_series("stale")], observations=[_observation("stale", "stale-1", NOW - timedelta(days=20), 80)],
    )
    expired = make_repository(
        root / "expired", target,
        series=[_series("expired")], observations=[_observation("expired", "expired-1", NOW - timedelta(days=2), 70)],
        expires="2026-11-05T03:59:59Z",
    )
    wrong = make_repository(
        root / "wrong-sku", target,
        series=[_series("sku-a", product="same-product", seller="seller-a", variant="sku-a"), _series("sku-b", product="same-product", seller="seller-b", variant="sku-b")],
        observations=[_observation("sku-a", "sku-a-1", NOW - timedelta(days=2), 100), _observation("sku-b", "sku-b-1", NOW - timedelta(days=2), 200)],
    )

    bundles: dict[str, dict[str, Any]] = {}
    for name, repository, key in (
        ("valid", valid, "valid"),
        ("incomplete", incomplete, "incomplete"),
        ("daily_median", daily, "daily-median"),
    ):
        bundles[name] = {
            "search": repository.search("", page=1, limit=20),
            "detail": repository.detail(key),
            "affiliate": repository.affiliate(key),
            "quality": repository.quality(key),
            "product_id": key,
        }
    return {
        "bundles": bundles,
        "zero": {"search": zero.search("", page=1, limit=20), "quality": zero.quality("zero")},
        "stale": {"search": stale.search("", page=1, limit=20), "quality": stale.quality("stale")},
        "expired": {"search": expired.search("", page=1, limit=20), "detail": expired.detail("expired"), "quality": expired.quality("expired")},
        "wrong_sku": {
            "search": wrong.search("same-product", page=1, limit=20),
            "details": [wrong.detail("sku-a"), wrong.detail("sku-b")],
        },
    }


def parser_cases(evidence: dict[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    bundles = evidence["bundles"]
    for name in ("valid", "incomplete", "daily_median"):
        bundle = bundles[name]
        for method in ("search", "detail", "affiliate"):
            result.append({
                "name": name,
                "method": method,
                "payload": bundle[method],
                "expected_product_id": bundle["product_id"],
            })
    return result
