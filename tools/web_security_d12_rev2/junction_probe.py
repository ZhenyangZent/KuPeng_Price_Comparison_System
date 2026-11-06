from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b15-root", type=Path, required=True)
    parser.add_argument("--nominal-project", type=Path, required=True)
    parser.add_argument("--outside-target", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.b15_root.resolve() / "services/private_observation_b15"))
    from private_observation_b15.store import ObservationStore, StoreError

    nominal = args.nominal_project.absolute()
    outside = args.outside_target.resolve(strict=True)
    requested = nominal / "data/private_user_observations_b15"
    before = sorted(path.relative_to(outside).as_posix() for path in outside.rglob("*.sqlite3"))
    rejected = False
    error_type = None
    error_message = None
    try:
        ObservationStore(requested, allowed_project_root=nominal)
    except StoreError as exc:
        rejected = True
        error_type = type(exc).__name__
        error_message = str(exc)
    after = sorted(path.relative_to(outside).as_posix() for path in outside.rglob("*.sqlite3"))
    evidence = {
        "schema": "CDH-D12-B15-REV2-WINDOWS-JUNCTION-PROBE-1",
        "platform": sys.platform,
        "requested_data_root": "<D12_REV2_PROBE>/nominal_project/data/private_user_observations_b15",
        "junction": "<D12_REV2_PROBE>/nominal_project/data -> <D12_REV2_PROBE>/outside_target",
        "constructor_rejected": rejected,
        "error_type": error_type,
        "error_message": error_message,
        "outside_sqlite_before": before,
        "outside_sqlite_after": after,
        "outside_sqlite_created_count": len(set(after) - set(before)),
        "gate": "PASS" if sys.platform == "win32" and rejected and before == after else "FAIL",
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
