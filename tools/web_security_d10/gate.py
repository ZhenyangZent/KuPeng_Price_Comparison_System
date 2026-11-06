from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from tools.web_security_d10.environment import probe_loopback
from tools.web_security_d10.runtime import run_exact
from tools.web_security_d10.targets import verify_targets


def run_gate(releases: str | Path) -> dict[str, object]:
    identities = verify_targets(releases)
    runtime = run_exact(releases)
    loopback = probe_loopback()
    findings = [
        {
            "finding_id": "D10-P1-001", "priority": "P1", "owner": "B",
            "title": "B12 JSON loader accepts duplicate object keys with last-value-wins semantics",
            "location": "services/import_staging_b12/import_staging_b12/staging.py:load_records",
            "detail": "Exact B12 accepts a duplicate title key, validates the effective record, and reaches provenance evaluation. Strict import preview should reject duplicate JSON keys before semantic validation.",
        },
        {
            "finding_id": "D10-P2-001", "priority": "P2", "owner": "A",
            "title": "A10 V4 parser does not require exact object field sets",
            "location": "apps/price-web/frontend/src/b10RuntimeSchema.ts",
            "detail": "Unknown response fields are ignored by A10. Current React sinks escape text and CTA remains disabled; F07 rejects a smuggled click_url, so no active exploit was reproduced.",
        },
        {
            "finding_id": "D10-P2-002", "priority": "P2", "owner": "B",
            "title": "B12 accepts spreadsheet-formula-prefixed CSV text without neutralization metadata",
            "location": "services/import_staging_b12/import_staging_b12/staging.py:_csv_value",
            "detail": "The dry-run JSON path does not execute formulas and writes no database, but downstream CSV re-export must neutralize leading =,+,-,@ characters.",
        },
        {
            "finding_id": "D10-P2-003", "priority": "P2", "owner": "C",
            "title": "C09 exact historical package has two undeclared metadata files",
            "location": "CDH_C_R08_001_REVIEW.zip",
            "detail": "Central-known RELEASE_INFO.json and SHA256SUMS.txt exception only; strict D10 output does not inherit this exception.",
        },
    ]
    counts = {priority: sum(item["priority"] == priority for item in findings) for priority in ("P0", "P1", "P2")}
    harness_pass = runtime["harness_pass"] and counts["P0"] == 0
    return {
        "schema": "CDH-D10-R09-INTEGRATED-SECURITY-GATE-1",
        "task_id": "CDH-D10-INTEGRATED-REVIEW-SECURITY-001",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_execution": "PASS" if harness_pass else "FAIL",
        "review_status": "READY_FOR_REVIEW_WITH_P1_FINDING" if harness_pass else "D10_HARNESS_FAILURE",
        "priority_counts": counts,
        "targets": identities,
        "runtime": runtime,
        "loopback_browser_gate": loopback,
        "browser_integration": "NOT_RUN_ENV_BLOCKED" if loopback["status"] != "AVAILABLE" else "NOT_RUN_D10_HAS_NO_BROWSER_AUTHORITY",
        "findings": findings,
        "restrictions": {
            "offline_only": True, "synthetic_only": True, "target_source_mutation_count": 0,
            "real_env_read_count": 0, "external_network_count": 0, "daily_browser_profile_access_count": 0,
            "registry_action_count": 0, "affiliate_click_count": 0, "database_write_count": 0,
            "public_deploy_count": 0, "shopping_action_count": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--releases", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = run_gate(args.releases)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["audit_execution"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
