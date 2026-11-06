from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
B16 = ROOT / "review" / "D13" / "002" / "input" / "CDH_B_R12_002_REVIEW"
sys.path.insert(0, str(B16 / "services" / "private_batch_import_b16"))
sys.path.insert(0, str(B16 / "services" / "private_observation_b15"))
from private_batch_import_b16.store import BatchObservationStore  # noqa: E402
from private_observation_b15.store import StoreError  # noqa: E402


def main() -> int:
    case = Path(sys.argv[1]).resolve()
    project = case / "project"
    junction = project / "private-data"
    outside = case / "outside"
    before = sorted(item.name for item in outside.iterdir())
    rejected = False
    error = None
    try:
        BatchObservationStore(junction, allowed_project_root=project, clock=lambda: datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc))
    except StoreError as exc:
        rejected = True
        error = str(exc)
    after = sorted(item.name for item in outside.iterdir())
    result = {"schema_version": "CDH-D13-B16-REV2-WINDOWS-JUNCTION-1", "platform": sys.platform, "junction_path": str(junction), "target_path": str(outside), "rejected": rejected, "error": error, "outside_entries_before": before, "outside_entries_after": after, "outside_write_count": len(set(after) - set(before))}
    evidence = ROOT / "review" / "D13" / "002" / "evidence" / "WINDOWS_JUNCTION_PROBE.json"
    evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if sys.platform == "win32" and rejected and result["outside_write_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
