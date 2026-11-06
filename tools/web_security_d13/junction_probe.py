from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
B16 = ROOT / "review" / "D13" / "001" / "input" / "CDH_B_R12_001_REVIEW"
sys.path.insert(0, str(B16 / "services" / "private_batch_import_b16"))
sys.path.insert(0, str(B16 / "services" / "private_observation_b15"))

from private_batch_import_b16.store import BatchObservationStore  # noqa: E402
from private_observation_b15.store import StoreError  # noqa: E402


def main() -> int:
    case = Path(sys.argv[1]).resolve()
    project = case / "project"
    junction = project / "private-data"
    outside = case / "outside"
    evidence = ROOT / "review" / "D13" / "001" / "evidence" / "WINDOWS_JUNCTION_PROBE.json"
    before = sorted(path.name for path in outside.iterdir()) if outside.exists() else []
    rejected = False
    error = None
    try:
        BatchObservationStore(
            junction,
            allowed_project_root=project,
            clock=lambda: datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc),
        )
    except StoreError as exc:
        rejected = True
        error = str(exc)
    after = sorted(path.name for path in outside.iterdir()) if outside.exists() else []
    result = {
        "schema_version": "CDH-D13-WINDOWS-JUNCTION-PROBE-1",
        "platform": sys.platform,
        "junction_path": str(junction),
        "target_path": str(outside),
        "rejected": rejected,
        "error": error,
        "outside_entries_before": before,
        "outside_entries_after": after,
        "outside_write_count": len(set(after) - set(before)),
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if sys.platform == "win32" and rejected and result["outside_write_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
