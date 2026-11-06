from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .crossline import assess_affiliate_bridge, assess_quality_integration
from .env_audit import audit_env_example
from .frontend import assess_frontend
from .models import Check, Finding
from .targets import read_unique_member, verify_target


EXPECTED_TARGETS = {
    "CDH_A06_001_REVIEW.zip": "d9fce75d876b86d5cbb28f77e8ff9354e9d38a5c9389abe10d2a2ddc46adefb5",
    "CDH_B06_001_REVIEW.zip": "d99284c7e6d422b16255b51d29aacb5034a1d43b254c4aca6fa389cef6caf3ae",
    "CDH_B07_001_REVIEW.zip": "f0a597f225233cd635e53c8646ce58ab20422250a8cb357650434eb59d342ee4",
    "CDH_C04_001_REVIEW.zip": "370ed70e20942693b185a540744cc5c1924502d147f7f576552703747d022ef1",
    "CDH_F02_001_REVIEW.zip": "89b4c21f9f28516052f0298b71d71c6d6f82f48daea5d91db81bcbb5815afd73",
}


def _text(path: Path, suffix: str) -> str:
    return read_unique_member(path, suffix).decode("utf-8-sig")


def run_gate(target_dir: str | Path) -> dict[str, object]:
    root = Path(target_dir)
    identities = []
    for name, expected in EXPECTED_TARGETS.items():
        identities.append(verify_target(root / name, expected_sha256=expected).as_dict())

    a06, b06, b07, c04, f02 = (root / name for name in EXPECTED_TARGETS)
    checks: list[Check] = []
    findings: list[Finding] = []

    c, f = assess_frontend(
        typescript_types=_text(a06, "apps/price-web/frontend/src/types.ts"),
        local_api=_text(a06, "apps/price-web/frontend/src/localApi.ts"),
        affiliate=_text(a06, "apps/price-web/frontend/src/affiliate.ts"),
        app=_text(a06, "apps/price-web/frontend/src/App.tsx"),
        vite_config=_text(a06, "apps/price-web/frontend/vite.config.ts"),
        index_html=_text(a06, "apps/price-web/frontend/index.html"),
        api_source=_text(b06, "services/price_query/price_query/api.py"),
    )
    checks.extend(c); findings.extend(f)
    c, f = audit_env_example(".env.example", read_unique_member(a06, "apps/price-web/frontend/.env.example"))
    checks.extend(c); findings.extend(f)
    c, f = assess_quality_integration(
        b07_schema=_text(b07, "services/price_quality/SCHEMA.md"),
        b07_compatibility=_text(b07, "services/price_quality/B06_V2_COMPATIBILITY.md"),
        frontend_types=_text(a06, "apps/price-web/frontend/src/types.ts"),
    )
    checks.extend(c); findings.extend(f)
    c, f = assess_affiliate_bridge(
        c04_readiness_raw=read_unique_member(c04, "research/affiliate_intake/CAPABILITY_READINESS.json"),
        f02_binding=_text(f02, "services/affiliate_binding_v2/affiliate_binding_v2/binding.py"),
        f02_contract=_text(f02, "services/affiliate_binding_v2/F02_V2_BINDING_CONTRACT.md"),
    )
    checks.extend(c); findings.extend(f)

    priority_counts = {priority: sum(item.priority == priority for item in findings) for priority in ("P0", "P1", "P2")}
    blocking = priority_counts["P0"] + priority_counts["P1"]
    return {
        "schema": "CDH-D05-WEB-SECURITY-GATE-1",
        "task_id": "CDH-D05-WEB-INTEGRATION-SECURITY-001",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_identity_gate": "PASS",
        "audit_execution": "PASS",
        "full_site_security_acceptance": "BLOCKED" if blocking else "PASS",
        "blocking_finding_count": blocking,
        "priority_counts": priority_counts,
        "targets": identities,
        "checks": [item.as_dict() for item in checks],
        "findings": [item.as_dict() for item in findings],
        "restrictions": {
            "offline_only": True,
            "target_code_mutated": False,
            "real_env_read": False,
            "live_network_count": 0,
            "browser_profile_access_count": 0,
            "affiliate_click_count": 0,
            "shopping_action_count": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline D05 cross-line web security gate")
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = run_gate(args.target_dir)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 2 if result["blocking_finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
