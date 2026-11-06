from __future__ import annotations

import sqlite3
from pathlib import Path


def coverage_values(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """SELECT
        (SELECT COUNT(*) FROM observations WHERE is_synthetic=0) AS real_observations,
        (SELECT COUNT(*) FROM observations WHERE is_synthetic=1) AS synthetic_observations,
        (SELECT COUNT(*) FROM leads WHERE is_synthetic=0) AS announcement_leads,
        (SELECT COUNT(*) FROM observations WHERE product_id IS NOT NULL AND variant_id IS NOT NULL AND seller_id IS NOT NULL) AS comparable_skus,
        (SELECT COUNT(*) FROM source_permissions p WHERE status='APPROVED' AND reviewed_at_utc=(SELECT MAX(reviewed_at_utc) FROM source_permissions p2 WHERE p2.source_id=p.source_id AND p2.operation=p.operation)) AS approved_automatic_sources,
        (SELECT COUNT(*) FROM quarantine) AS quarantined_entries,
        (SELECT COUNT(*) FROM ingest_attempts WHERE status='DUPLICATE_NOOP') AS duplicate_noops"""
    ).fetchone()
    return {key: row[key] for key in row.keys()}


def write_coverage_report(conn: sqlite3.Connection, path: Path, *, data_as_of: str) -> None:
    values = coverage_values(conn)
    text = f"""# D01 Data Coverage Report

DATA_AS_OF_UTC: `{data_as_of}`
SCHEMA_VERSION: `CDH-EXCHANGE-1`
LIVE_COUPANG_DISCOVERY: `SOURCE_BLOCKED`

REAL_USER_OBSERVATION_COUNT: `{values['real_observations']}`
SYNTHETIC_OBSERVATION_COUNT: `{values['synthetic_observations']}`
PUBLIC_ANNOUNCEMENT_CLUE_COUNT: `{values['announcement_leads']}`
FULLY_COMPARABLE_SKU_COUNT: `{values['comparable_skus']}`
APPROVED_AUTOMATIC_SOURCE_COUNT: `{values['approved_automatic_sources']}`
QUARANTINED_ENTRY_COUNT: `{values['quarantined_entries']}`
DUPLICATE_NOOP_COUNT: `{values['duplicate_noops']}`

`USER_ENTERED` / `USER_FILE` records are user observations, not verified checkout transactions. `PROMO_CLUE` records are excluded from price history. Synthetic observations remain visibly marked and are excluded from real-observation counts. Unknown membership, shipping, coupon, stock, and mandatory-fee facts remain `UNKNOWN` / `UNVERIFIED`.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

