from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
sys.path.insert(0, str(APP_ROOT))

from a01_app.i02_preview import SyntheticSyncPreview


def main() -> int:
    parser = argparse.ArgumentParser(description="I02 malformed receipt/snapshot recovery evidence")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    workspace = (PROJECT_ROOT / "experiments/I02/recovery_evidence").resolve()
    allowed = (PROJECT_ROOT / "experiments/I02").resolve()
    workspace.relative_to(allowed)
    if workspace.exists():
        shutil.rmtree(workspace)
    service = SyntheticSyncPreview(root=PROJECT_ROOT, workspace=workspace)
    initial = service.run_cycle()
    receipt = workspace / "data/exchange/receipts/latest.json"
    snapshot = workspace / "data/exchange/snapshots/latest.json"
    cases = []

    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["entries"][0]["status"] = []
    receipt.write_text(json.dumps(value), encoding="utf-8")
    broken_status = service.read_status()
    repaired_status = service.run_cycle(seed_first=False)
    cases.append({"case": "MALFORMED_STATUS_ARRAY", "before": broken_status.state, "after": repaired_status.state})

    snapshot.write_bytes(b"{}")
    mismatched_status = service.read_status()
    repaired_snapshot = service.run_cycle(seed_first=False)
    cases.append({"case": "SNAPSHOT_MISMATCH", "before": mismatched_status.state, "after": repaired_snapshot.state})

    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["receipt_version"] = "CDH-D01-RECEIPT-2"
    receipt.write_text(json.dumps(value), encoding="utf-8")
    incompatible_status = service.read_status()
    repaired_version = service.run_cycle(seed_first=False)
    cases.append({"case": "RECEIPT_VERSION_MISMATCH", "before": incompatible_status.state, "after": repaired_version.state})

    expected = [
        ("MALFORMED_STATUS_ARRAY", "UNKNOWN", "READY"),
        ("SNAPSHOT_MISMATCH", "SYNCING", "READY"),
        ("RECEIPT_VERSION_MISMATCH", "UNKNOWN", "READY"),
    ]
    observed = [(item["case"], item["before"], item["after"]) for item in cases]
    result = {
        "task_id": "CDH-I02-LOCAL-SYNC-PREVIEW-001",
        "initial_state": initial.state,
        "workspace": str(workspace),
        "cases": cases,
        "result": "PASS" if initial.state == "READY" and observed == expected else "FAIL",
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
