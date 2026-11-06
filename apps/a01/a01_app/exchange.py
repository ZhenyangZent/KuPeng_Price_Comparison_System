from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .constants import EXCHANGE_VERSION, MAX_SUBMISSION_BYTES
from .schema import format_utc, validate_submission


class DuplicateSubmissionError(FileExistsError):
    pass


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def build_submission(
    *,
    product_title: str,
    displayed_price_twd: int,
    observed_at: datetime,
    url: str | None = None,
    product_id: str | None = None,
    variant_id: str | None = None,
    seller_id: str | None = None,
    minimum_purchase_quantity: int | None = None,
    shipping_status: str = "UNKNOWN",
    shipping_fee_twd: int | None = None,
    stock_status: str = "UNKNOWN",
    coupon_status: str = "UNKNOWN",
    account_eligibility_status: str = "UNKNOWN",
    mandatory_fee_status: str = "UNKNOWN",
    notes: str = "",
    is_synthetic: bool = False,
    submission_id: str | None = None,
    created_at: datetime | None = None,
    source_kind: str | None = None,
) -> dict[str, object]:
    created = created_at or datetime.now(timezone.utc)
    kind = source_kind or ("SYNTHETIC_TEST" if is_synthetic else "USER_ENTERED")
    permission = "SYNTHETIC_ONLY" if kind == "SYNTHETIC_TEST" else "USER_PROVIDED_ONLY"
    record = {
        "schema_version": EXCHANGE_VERSION,
        "submission_id": submission_id or str(uuid.uuid4()),
        "record_type": "USER_PRICE_OBSERVATION",
        "created_at_utc": format_utc(created),
        "observed_at_utc": format_utc(observed_at),
        "source": {
            "source_kind": kind,
            "permission_scope": permission,
            "url": url,
            "note": "使用者自行輸入；僅保存觀測，不代表結帳或平台驗證" if not is_synthetic else "合成測試；禁止當真實優惠",
        },
        "offer": {
            "platform": "TW_COUPANG",
            "product_title": product_title,
            "product_id": product_id,
            "variant_id": variant_id,
            "seller_id": seller_id,
            "displayed_price_twd": displayed_price_twd,
            "price_basis": "DISPLAYED_UNKNOWN",
            "minimum_purchase_quantity": minimum_purchase_quantity,
            "shipping_status": shipping_status,
            "shipping_fee_twd": shipping_fee_twd,
            "stock_status": stock_status,
            "coupon_status": coupon_status,
            "account_eligibility_status": account_eligibility_status,
            "mandatory_fee_status": mandatory_fee_status,
            "notes": notes,
        },
        "is_synthetic": is_synthetic,
    }
    return validate_submission(record, now=created)


def safe_write_submission(inbox: Path, value: object) -> tuple[Path, str]:
    validated = validate_submission(value)
    payload = canonical_json_bytes(validated)
    if len(payload) > MAX_SUBMISSION_BYTES:
        raise ValueError("SUBMISSION_TOO_LARGE")
    inbox.mkdir(parents=True, exist_ok=True)
    inbox = inbox.resolve()
    submission_id = str(validated["submission_id"])
    target = inbox / f"submission_{submission_id}.json"
    if target.exists():
        raise DuplicateSubmissionError(submission_id)
    temporary = inbox / f".submission_{submission_id}.{secrets.token_hex(8)}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if os.name == "nt":
                # Windows rename is an atomic create and refuses an existing target.
                os.rename(temporary, target)
            else:
                # POSIX rename may overwrite, so a same-filesystem hard link supplies
                # atomic create-if-absent semantics before the temporary is removed.
                os.link(temporary, target)
                temporary.unlink()
        except FileExistsError as exc:
            raise DuplicateSubmissionError(submission_id) from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return target, hashlib.sha256(payload).hexdigest()


def count_pending(inbox: Path) -> int:
    if not inbox.exists():
        return 0
    return sum(1 for path in inbox.glob("submission_*.json") if path.is_file())
