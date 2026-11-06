from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .model import SCHEMA_VERSION, utc_now_text


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(20):
            try:
                os.replace(tmp_name, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.005 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def build_snapshot(conn: sqlite3.Connection, generated_at_utc: str | None = None) -> dict[str, object]:
    generated = generated_at_utc or utc_now_text()
    counts = conn.execute(
        """SELECT
        (SELECT COUNT(*) FROM observations) + (SELECT COUNT(*) FROM leads) AS total_entries,
        (SELECT COUNT(*) FROM observations WHERE is_synthetic=0) AS real_observations,
        (SELECT COUNT(*) FROM observations WHERE is_synthetic=1) AS synthetic_observations,
        (SELECT COUNT(*) FROM leads WHERE qualification_state='UNVERIFIED') AS unverified_leads"""
    ).fetchone()
    rows = conn.execute(
        """SELECT submission_id, 'USER_PRICE_OBSERVATION' AS record_type, observed_at_utc,
        product_title, displayed_price_twd, is_synthetic, qualification_state, source_kind, source_url
        FROM observations
        UNION ALL
        SELECT submission_id, 'PROMO_CLUE', observed_at_utc, product_title, NULL,
        is_synthetic, qualification_state, source_kind, source_url FROM leads
        ORDER BY observed_at_utc DESC, submission_id"""
    ).fetchall()
    permission_checked = conn.execute("SELECT MAX(reviewed_at_utc) AS reviewed FROM source_permissions").fetchone()["reviewed"]
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_generated_at_utc": generated,
        "source": "D01_LOCAL_LEDGER",
        "counts": {key: counts[key] for key in counts.keys()},
        "items": [
            {
                "submission_id": row["submission_id"],
                "record_type": row["record_type"],
                "observed_at_utc": row["observed_at_utc"],
                "product_title": row["product_title"],
                "displayed_price_twd": row["displayed_price_twd"],
                "is_synthetic": bool(row["is_synthetic"]),
                "qualification_state": row["qualification_state"],
                "source_kind": row["source_kind"],
                "source_url": row["source_url"],
            }
            for row in rows
        ],
        "source_status": {
            "live_coupang_discovery": "SOURCE_BLOCKED",
            "permission_checked_at_utc": permission_checked,
        },
    }


def write_snapshot(conn: sqlite3.Connection, output_dir: Path, generated_at_utc: str | None = None) -> tuple[Path, str]:
    snapshot = build_snapshot(conn, generated_at_utc)
    data = (json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    dt = datetime.fromisoformat(str(snapshot["snapshot_generated_at_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    version_name = f"snapshot_{dt.strftime('%Y%m%dT%H%M%SZ')}_{digest[:12]}.json"
    version_path = output_dir / version_name
    _atomic_write(version_path, data)
    _atomic_write(output_dir / "latest.json", data)
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO snapshots(snapshot_sha256, generated_at_utc, schema_version, relative_path, item_count)
            VALUES(?,?,?,?,?)""",
            (digest, snapshot["snapshot_generated_at_utc"], SCHEMA_VERSION, version_name, snapshot["counts"]["total_entries"]),
        )
    return version_path, digest
