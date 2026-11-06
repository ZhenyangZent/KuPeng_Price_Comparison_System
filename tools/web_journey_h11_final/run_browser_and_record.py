from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "review" / "H11_FINAL" / "evidence"
OUT = EVIDENCE / "BROWSER_PROCESS_RECEIPT.json"


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    command = ["node", "tools/web_journey_h11/run_actual_h11.mjs"]
    environment = {**os.environ, "CDH_H11_FINAL": "1"}
    completed = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True, encoding="utf-8", errors="replace", check=False)
    result = {
        "task_id": "H11", "revision": "FINAL_OFFICIAL_LAUNCHER", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": command, "environment": {"CDH_H11_FINAL": "1"}, "exit_code": completed.returncode,
        "stdout": completed.stdout, "stderr": completed.stderr, "status": "PASS" if completed.returncode == 0 else "FAIL",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
