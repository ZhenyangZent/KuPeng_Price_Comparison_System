from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from tools.web_security_d08.gate import run_gate as run_d08
from tools.web_security_d06.targets import verify_target
from tools.web_security_d09.exact_runtime import run_exact_pair
from tools.web_security_d09.portable import verify_review_target


HASHES = {
    "A09": "96d239e4a3bb5ca57624c0b8d6e06344ad68b6482b13d8ee9b72a8f1997ebbde",
    "B10": "dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549",
    "F05": "8a90dd7c8d6212ec1d54a9e2c6004cdf25d5f7cc92636011b52e1ead6ed94dfc",
    "B11": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
    "F06": "c2db9aa981cbc935b52944516d5b4259829ffa5af892ac3dc7d28fc6b022ac89",
}


def run_gate(releases: Path, r07_bundle: Path) -> dict[str, object]:
    paths = {
        "A09": releases / "CDH_A_R06_001_REVIEW.zip",
        "B10": releases / "CDH_B_R06_001_REVIEW.zip",
        "F05": releases / "CDH_F_R06_001_REVIEW.zip",
        "B11": releases / "CDH_B_R07_001_REVIEW.zip",
        "F06": releases / "CDH_F_R07_001_REVIEW.zip",
    }
    identities = {
        role: (
            verify_target(paths[role], expected_sha256=HASHES[role])
            if role == "F05"
            else verify_review_target(paths[role], HASHES[role])
        ).as_dict()
        for role in paths
    }
    if identities["F05"]["manifest_undeclared"] != ("CDH_F_R06_001_REVIEW/SHA256SUMS.txt",):
        raise ValueError("F05_LEGACY_AUXILIARY_FILE_MISMATCH")
    baseline = run_d08(paths["A09"], paths["B10"], paths["F05"], r07_bundle)
    exact = run_exact_pair(paths["B11"], paths["F06"])
    baseline_pass = baseline["audit_execution"] == "PASS" and baseline["priority_counts"] == {"P0": 0, "P1": 3, "P2": 1} and baseline["unexpected_failures"] == []
    result = {
        "schema": "CDH-D09-R08-PORTABLE-B11-SECURITY-GATE-1",
        "task_id": "CDH-D09-PORTABLE-ZIP-VERIFIER-AND-B11-SECURITY-001",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if baseline_pass and exact["passed"] else "FAIL",
        "portable_targets": identities,
        "legacy_exception": {"role": "F05", "path": "CDH_F_R06_001_REVIEW/SHA256SUMS.txt", "reason": "exact historical D08 baseline auxiliary checksum file; not accepted by strict D09 verifier"},
        "d08_baseline": {"passed": baseline_pass, "priority_counts": baseline["priority_counts"], "unexpected_failures": baseline["unexpected_failures"]},
        "b11_f06_exact_runtime": exact,
        "a10_b11_full_site_integration": "NOT_RUN_INPUT_NOT_CENTRALLY_ACKNOWLEDGED",
        "restrictions": {
            "offline_only": True, "synthetic_only": True, "target_source_mutation_count": 0,
            "real_env_read_count": 0, "live_network_count": 0, "browser_profile_access_count": 0,
            "registry_action_count": 0, "affiliate_click_count": 0, "shopping_action_count": 0,
            "public_deploy_count": 0,
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--releases", type=Path, required=True)
    parser.add_argument("--r07-bundle", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = run_gate(args.releases, args.r07_bundle)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
