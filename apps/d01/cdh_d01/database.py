from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .model import ValidatedRecord, utc_now_text


MIGRATION_001 = """
CREATE TABLE IF NOT EXISTS schema_migrations(
  version INTEGER PRIMARY KEY,
  applied_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_submissions(
  raw_submission_id INTEGER PRIMARY KEY,
  submission_id TEXT NOT NULL,
  raw_sha256 TEXT NOT NULL CHECK(length(raw_sha256)=64),
  source_path TEXT NOT NULL,
  source_id TEXT,
  source_kind TEXT NOT NULL,
  received_at_utc TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  UNIQUE(submission_id, raw_sha256)
);
CREATE INDEX IF NOT EXISTS idx_raw_submission_id ON raw_submissions(submission_id);
CREATE TABLE IF NOT EXISTS observations(
  observation_id INTEGER PRIMARY KEY,
  raw_submission_id INTEGER NOT NULL UNIQUE REFERENCES raw_submissions(raw_submission_id),
  submission_id TEXT NOT NULL,
  observed_at_utc TEXT NOT NULL,
  imported_at_utc TEXT NOT NULL,
  source_id TEXT,
  source_kind TEXT NOT NULL,
  permission_scope TEXT NOT NULL,
  source_url TEXT,
  product_title TEXT NOT NULL,
  product_id TEXT,
  variant_id TEXT,
  seller_id TEXT,
  displayed_price_twd INTEGER NOT NULL CHECK(displayed_price_twd >= 0),
  price_basis TEXT NOT NULL,
  minimum_purchase_quantity INTEGER,
  shipping_status TEXT NOT NULL,
  shipping_fee_twd INTEGER,
  stock_status TEXT NOT NULL,
  coupon_status TEXT NOT NULL,
  account_eligibility_status TEXT NOT NULL,
  mandatory_fee_status TEXT NOT NULL,
  qualification_state TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK(qualification_state='UNVERIFIED'),
  is_synthetic INTEGER NOT NULL CHECK(is_synthetic IN (0,1)),
  notes TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observation_identity_time ON observations(product_id, variant_id, seller_id, price_basis, observed_at_utc);
CREATE INDEX IF NOT EXISTS idx_observation_real ON observations(is_synthetic, observed_at_utc);
CREATE TABLE IF NOT EXISTS leads(
  lead_id INTEGER PRIMARY KEY,
  raw_submission_id INTEGER NOT NULL UNIQUE REFERENCES raw_submissions(raw_submission_id),
  submission_id TEXT NOT NULL,
  observed_at_utc TEXT NOT NULL,
  published_at_utc TEXT,
  imported_at_utc TEXT NOT NULL,
  source_id TEXT,
  source_kind TEXT NOT NULL,
  permission_scope TEXT NOT NULL,
  source_url TEXT,
  product_title TEXT NOT NULL,
  promo_claim TEXT NOT NULL,
  qualification_state TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK(qualification_state='UNVERIFIED'),
  is_synthetic INTEGER NOT NULL CHECK(is_synthetic IN (0,1))
);
CREATE TABLE IF NOT EXISTS ingest_attempts(
  attempt_id INTEGER PRIMARY KEY,
  attempted_at_utc TEXT NOT NULL,
  source_path TEXT NOT NULL,
  raw_sha256 TEXT,
  submission_id TEXT,
  status TEXT NOT NULL,
  reason_code TEXT,
  reason_detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempt_status_time ON ingest_attempts(status, attempted_at_utc);
CREATE TABLE IF NOT EXISTS quarantine(
  quarantine_id INTEGER PRIMARY KEY,
  quarantined_at_utc TEXT NOT NULL,
  source_path TEXT NOT NULL,
  raw_sha256 TEXT,
  submission_id TEXT,
  reason_code TEXT NOT NULL,
  reason_detail TEXT NOT NULL,
  conflicting_raw_sha256 TEXT
);
CREATE TABLE IF NOT EXISTS source_permissions(
  permission_id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  evidence_url TEXT,
  evidence_summary TEXT NOT NULL,
  scope TEXT NOT NULL,
  reviewed_at_utc TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('PENDING','RESTRICTED','UNVERIFIED','DOCUMENT_RESEARCH_ONLY','POLICY_REFERENCE_ONLY','LOCAL_ONLY','NOT_APPLICABLE','APPROVED')),
  quota TEXT NOT NULL,
  UNIQUE(source_id, operation, reviewed_at_utc)
);
CREATE INDEX IF NOT EXISTS idx_permission_current ON source_permissions(source_id, operation, reviewed_at_utc DESC);
CREATE TABLE IF NOT EXISTS snapshots(
  snapshot_id INTEGER PRIMARY KEY,
  snapshot_sha256 TEXT NOT NULL UNIQUE,
  generated_at_utc TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  relative_path TEXT NOT NULL UNIQUE,
  item_count INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS raw_submissions_no_update BEFORE UPDATE ON raw_submissions BEGIN SELECT RAISE(ABORT, 'raw_submissions append-only'); END;
CREATE TRIGGER IF NOT EXISTS raw_submissions_no_delete BEFORE DELETE ON raw_submissions BEGIN SELECT RAISE(ABORT, 'raw_submissions append-only'); END;
CREATE TRIGGER IF NOT EXISTS observations_no_update BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT, 'observations append-only'); END;
CREATE TRIGGER IF NOT EXISTS observations_no_delete BEFORE DELETE ON observations BEGIN SELECT RAISE(ABORT, 'observations append-only'); END;
CREATE TRIGGER IF NOT EXISTS leads_no_update BEFORE UPDATE ON leads BEGIN SELECT RAISE(ABORT, 'leads append-only'); END;
CREATE TRIGGER IF NOT EXISTS leads_no_delete BEFORE DELETE ON leads BEGIN SELECT RAISE(ABORT, 'leads append-only'); END;
"""

MIGRATION_002 = """
CREATE TABLE IF NOT EXISTS sync_file_outcomes(
  outcome_id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL,
  file_sha256 TEXT NOT NULL CHECK(length(file_sha256)=64),
  submission_id TEXT,
  status TEXT NOT NULL CHECK(status IN ('IMPORTED','DUPLICATE_NOOP','QUARANTINED')),
  reason_code TEXT,
  reason_detail TEXT,
  processed_at_utc TEXT NOT NULL,
  UNIQUE(filename, file_sha256)
);
CREATE INDEX IF NOT EXISTS idx_sync_outcome_filename ON sync_file_outcomes(filename, outcome_id DESC);
CREATE TRIGGER IF NOT EXISTS sync_file_outcomes_no_update BEFORE UPDATE ON sync_file_outcomes
BEGIN SELECT RAISE(ABORT, 'sync_file_outcomes append-only'); END;
CREATE TRIGGER IF NOT EXISTS sync_file_outcomes_no_delete BEFORE DELETE ON sync_file_outcomes
BEGIN SELECT RAISE(ABORT, 'sync_file_outcomes append-only'); END;
"""


def connect(path: Path, *, timeout: float = 5.0) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=%d" % int(timeout * 1000))
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(MIGRATION_001)
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc) VALUES(1, ?)", (utc_now_text(),))
        conn.executescript(MIGRATION_002)
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc) VALUES(2, ?)", (utc_now_text(),))


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def latest_permission_status(conn: sqlite3.Connection, source_id: str, operation: str) -> str | None:
    row = conn.execute(
        "SELECT status FROM source_permissions WHERE source_id=? AND operation=? ORDER BY reviewed_at_utc DESC, permission_id DESC LIMIT 1",
        (source_id, operation),
    ).fetchone()
    return row["status"] if row else None


def automatic_operation_allowed(conn: sqlite3.Connection, source_id: str, operation: str) -> bool:
    return latest_permission_status(conn, source_id, operation) == "APPROVED"


def insert_permission_rows(conn: sqlite3.Connection, rows: Iterable[dict[str, str]]) -> int:
    count = 0
    with conn:
        for row in rows:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO source_permissions
                (source_id, operation, evidence_url, evidence_summary, scope, reviewed_at_utc, status, quota)
                VALUES(?,?,?,?,?,?,?,?)""",
                (
                    row["source_id"], row["operation"], row.get("evidence_url"), row["evidence_summary"],
                    row["scope"], row["reviewed_at_utc"], row["status"], row.get("quota", "UNKNOWN"),
                ),
            )
            count += cursor.rowcount
    return count


def canonical_raw_json(record: ValidatedRecord) -> str:
    normalized = {
        "schema_version": "CDH-EXCHANGE-1",
        "submission_id": record.submission_id,
        "record_type": record.record_type,
        "created_at_utc": record.created_at_utc,
        "observed_at_utc": record.observed_at_utc,
        "published_at_utc": record.published_at_utc,
        "promo_claim": record.promo_claim,
        "source": {
            "source_id": record.source_id,
            "source_kind": record.source_kind,
            "permission_scope": record.permission_scope,
            "url": record.source_url,
            "note": record.source_note,
        },
        "offer": {
            "platform": "TW_COUPANG",
            "product_title": record.product_title,
            "product_id": record.product_id,
            "variant_id": record.variant_id,
            "seller_id": record.seller_id,
            "displayed_price_twd": record.displayed_price_twd,
            "price_basis": record.price_basis,
            "minimum_purchase_quantity": record.minimum_purchase_quantity,
            "shipping_status": record.shipping_status,
            "shipping_fee_twd": record.shipping_fee_twd,
            "stock_status": record.stock_status,
            "coupon_status": record.coupon_status,
            "account_eligibility_status": record.account_eligibility_status,
            "mandatory_fee_status": record.mandatory_fee_status,
            "notes": record.notes,
        },
        "is_synthetic": record.is_synthetic,
    }
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
