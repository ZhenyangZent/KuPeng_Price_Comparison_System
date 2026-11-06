from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from a01_app.exchange import build_submission, safe_write_submission


def independent_d01_parser(path: Path) -> dict:
    """Intentionally does not import the A01 schema validator."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"schema_version","submission_id","record_type","created_at_utc","observed_at_utc","source","offer","is_synthetic"}
    assert data["schema_version"] == "CDH-EXCHANGE-1"
    assert str(uuid.UUID(data["submission_id"])) == data["submission_id"]
    assert data["record_type"] == "USER_PRICE_OBSERVATION"
    assert data["source"]["source_kind"] == "USER_ENTERED"
    assert data["source"]["permission_scope"] == "USER_PROVIDED_ONLY"
    assert data["offer"]["platform"] == "TW_COUPANG"
    assert isinstance(data["offer"]["displayed_price_twd"], int) and not isinstance(data["offer"]["displayed_price_twd"], bool)
    assert data["offer"]["shipping_status"] == "UNKNOWN"
    assert data["offer"]["shipping_fee_twd"] is None
    assert data["is_synthetic"] is False
    return data


class IndependentContractTests(unittest.TestCase):
    def test_a01_submission_is_accepted_by_independent_d01_parser(self):
        now = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            record = build_submission(product_title="Contract test", displayed_price_twd=0, observed_at=now, created_at=now)
            path, _ = safe_write_submission(Path(temporary), record)
            parsed = independent_d01_parser(path)
            self.assertEqual(parsed["offer"]["displayed_price_twd"], 0)

    def test_fixture_snapshot_fields_match_independent_expectation(self):
        root = Path(__file__).resolve().parents[2]
        fixture_path = root / "input/orchestrator_bundles/A01/extracted/11_SYNTHETIC_SNAPSHOT_FIXTURE.json"
        if not fixture_path.exists():
            fixture_path = root / "input_contract/11_SYNTHETIC_SNAPSHOT_FIXTURE.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(fixture["schema_version"], "CDH-EXCHANGE-1")
        self.assertEqual(fixture["source"], "D01_LOCAL_LEDGER")
        self.assertEqual(fixture["source_status"]["live_coupang_discovery"], "SOURCE_BLOCKED")
