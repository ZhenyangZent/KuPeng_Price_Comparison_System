from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from datetime import timedelta
from pathlib import Path


def _load_test_helpers(backend_root: Path):
    test_path = backend_root / "tests" / "web" / "price_query_v3" / "test_adapter.py"
    spec = importlib.util.spec_from_file_location("g04_b08_exact_test_helpers", test_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load B release helpers: {test_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(backend_root: Path, output: Path, temp_root: Path) -> dict:
    helper = _load_test_helpers(backend_root.resolve())
    if temp_root.exists(): shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True)
    cases: dict[str, dict] = {}

    valid_root = temp_root / "valid"; valid_root.mkdir()
    valid = helper.repo(valid_root)
    cases["valid"] = {"search": valid.search("", page=1, limit=20), "detail": valid.detail("series-1"), "affiliate": valid.affiliate("series-1"), "quality": valid.quality("series-1")}

    incomplete_root = temp_root / "incomplete"; incomplete_root.mkdir()
    incomplete_series = [{
        "series_key": "series-1", "title": "Synthetic incomplete identity", "platform": "COUPANG_TW",
        "product_id": "product-1", "seller_id": None, "variant_id": "sku-1", "spec_signature": "size=1",
        "minimum_purchase_quantity": 1, "package_signature": "1x", "item_condition": "NEW",
        "price_basis": "CURRENT_ITEM_PRICE", "identity_state": "INCOMPLETE", "exact_match_claim_allowed": 0,
        "shipping_status": "UNKNOWN", "data_classification": "SYNTHETIC_FIXTURE", "source_kind": "SYNTHETIC",
        "quality_flags_json": "[]",
    }]
    incomplete = helper.repo(incomplete_root, series=incomplete_series)
    cases["incomplete"] = {"search": incomplete.search("", page=1, limit=20), "detail": incomplete.detail("series-1"), "affiliate": incomplete.affiliate("series-1"), "quality": incomplete.quality("series-1")}

    median_root = temp_root / "daily_median"; median_root.mkdir()
    base = helper.NOW - timedelta(days=2, hours=2)
    observations = []
    for index, price in enumerate((10, 20, 30)):
        # B08 intentionally takes the first sample per UTC hour before the daily median.
        when = base + timedelta(hours=index)
        observations.append({
            "series_key": "series-1", "submission_id": f"median-{index}",
            "observed_at_utc": when.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "taipei_date": (when + timedelta(hours=8)).date().isoformat(), "price_twd": price,
            "source_type": "SYNTHETIC", "source_id": f"median-{index}",
            "data_classification": "SYNTHETIC_FIXTURE", "is_synthetic": 1,
        })
    median = helper.repo(median_root, observations=observations)
    cases["daily_median"] = {"search": median.search("", page=1, limit=20), "detail": median.detail("series-1"), "affiliate": median.affiliate("series-1"), "quality": median.quality("series-1")}

    payload = {"schema": "CDH-G04-A-B-CROSSLINE-FIXTURES-1", "classification": "CONTRACT_FIXTURE_TEST_ONLY", "cases": cases}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path, required=True)
    args = parser.parse_args()
    build(args.backend_root, args.output, args.temp_root)
