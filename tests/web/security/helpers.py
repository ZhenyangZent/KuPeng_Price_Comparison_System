from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


NOW = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)


def workspace() -> Path:
    root = Path("review/D03_WEB/001/test_tmp") / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def summary(**changes: Any) -> dict[str, Any]:
    value = {
        "id": "product-1",
        "title": "Synthetic safe title",
        "variant_signature": "sku-1|seller-1|NEW|1ea",
        "sku_id": "sku-1",
        "last_observed_price_twd": 199,
        "last_observed_at": "2026-11-05T00:00:00Z",
        "observed_days": 3,
        "shipping_status": "UNKNOWN",
        "price_basis": "GENERAL_OBSERVED",
        "thumbnail": None,
        "source_type": "USER_FILE",
    }
    value.update(changes)
    return value


def search_response(*items: dict[str, Any], **changes: Any) -> dict[str, Any]:
    value = {
        "schema_version": "CDH-WEB-CONTRACT-V1",
        "items": list(items or (summary(),)),
        "page": 1,
        "limit": 20,
        "total": len(items or (summary(),)),
        "data_source_status": "USER_RECORDED_ONLY",
    }
    value.update(changes)
    return value


def affiliate(**changes: Any) -> dict[str, Any]:
    value = {
        "state": "VERIFIED",
        "click_url": "https://partners.example.invalid/click/product-1/sku-1",
        "verified_product_match": True,
        "provider_status": "VERIFIED",
        "provider_id": "synthetic-tw-provider",
        "provider_market": "TW",
        "disclosure_present": True,
        "link_source": "OFFICIAL_PROVIDER",
        "bound_product_id": "product-1",
        "bound_sku_id": "sku-1",
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "verified_at": (NOW - timedelta(minutes=5)).isoformat(),
    }
    value.update(changes)
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
