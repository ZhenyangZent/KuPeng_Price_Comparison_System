from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "web_journey_h10" / "run_actual_h10_rev2.mjs"
OUT = ROOT / "review" / "H10_REV2" / "evidence" / "BROWSER_PROCESS_RECEIPT.json"


def main() -> None:
    completed = subprocess.run(["node", str(SCRIPT)], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False)
    payload = {
        "task_id": "CDH-H10-PRIVATE-HISTORY-REOPEN-E2E-001",
        "revision": "REV2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": ["node", "tools/web_journey_h10/run_actual_h10_rev2.mjs"],
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
