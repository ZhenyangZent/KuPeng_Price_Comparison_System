from __future__ import annotations

from pathlib import Path


APP_VERSION = "0.5.0-a04-daily-local"
EXCHANGE_VERSION = "CDH-EXCHANGE-1"
RECEIPT_VERSION = "CDH-D01-RECEIPT-1"
SOURCE_AUTHORITY_STATUS = "SOURCE_BLOCKED"
MAX_SUBMISSION_BYTES = 1 * 1024 * 1024
MAX_IMPORT_BYTES = 1 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 50 * 1024 * 1024
MAX_RECEIPT_BYTES = 5 * 1024 * 1024
MAX_RECEIPT_ENTRIES = 10_000
SNAPSHOT_STALE_HOURS = 24
RECEIPT_STALE_HOURS = 24


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_inbox() -> Path:
    return project_root() / "data" / "exchange" / "inbox"


def default_snapshot() -> Path:
    return project_root() / "data" / "exchange" / "snapshots" / "latest.json"


def default_receipt() -> Path:
    return project_root() / "data" / "exchange" / "receipts" / "latest.json"


def default_state_dir() -> Path:
    return project_root() / "apps" / "a01" / "local_state"


def default_d04_report() -> Path:
    return project_root() / "data" / "exchange" / "reports" / "d04" / "latest.json"
