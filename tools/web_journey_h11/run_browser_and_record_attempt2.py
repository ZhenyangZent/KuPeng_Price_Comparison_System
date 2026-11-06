from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "review" / "H11" / "attempt2" / "evidence"
OUT = EVIDENCE / "BROWSER_PROCESS_RECEIPT.json"


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    command = ["node", "tools/web_journey_h11/run_actual_h11.mjs"]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace", check=False)
    result = {
        "task_id": "H11",
        "attempt": 2,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "attempt1_preserved": "review/H11/evidence",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
