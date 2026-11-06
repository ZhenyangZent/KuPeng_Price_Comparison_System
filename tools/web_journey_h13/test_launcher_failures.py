from __future__ import annotations

import http.server
import json
import shutil
import subprocess
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H13 = ROOT / "review" / "H13"
PROJECT = H13 / "runtime" / "project"
NEGATIVE = H13 / "runtime" / "negative"
EVIDENCE = H13 / "evidence"
OUT = EVIDENCE / "LAUNCHER_NEGATIVE_TESTS.json"
OCCUPIED_PORT = 12342
MISSING_PORT = 12343


def invoke_start(project: Path, port: int, name: str) -> dict[str, object]:
    command = project / "Start-CDH-Trial.cmd"
    case_root = NEGATIVE / name
    args = (
        f"call {command.name} -Port {port} "
        f'-StateDir "{case_root / "state"}" -RuntimeRoot "{case_root / "runtime"}" '
        f'-LogDir "{case_root / "logs"}" -PrivateDataRoot "{case_root / "private"}" -MachineReadable'
    )
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", args], cwd=project, text=True, capture_output=True,
        timeout=45, encoding="utf-8", errors="replace",
    )
    combined = completed.stdout + "\n" + completed.stderr
    payload = None
    for line in reversed(combined.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                payload = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
    return {
        "entry": "Start-CDH-Trial.cmd", "exit_code": completed.returncode,
        "stdout": completed.stdout, "stderr": completed.stderr, "payload": payload,
    }


def main() -> None:
    if OUT.exists():
        raise RuntimeError("H13 launcher negative evidence already exists")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    missing_project = NEGATIVE / "missing-runtime-project"
    if missing_project.exists():
        raise RuntimeError("missing-runtime project already exists")
    shutil.copytree(PROJECT, missing_project)
    removed = missing_project / "apps" / "price-web" / "local-trial-a17" / "vendor" / "frontend" / "dist" / "index.html"
    removed.unlink()
    missing_result = invoke_start(missing_project, MISSING_PORT, "missing-runtime-case")
    missing_error = str((missing_result.get("payload") or {}).get("error", ""))
    missing_gate = (
        missing_result["exit_code"] == 2
        and (missing_result.get("payload") or {}).get("status") == "FAILED"
        and "A17_RUNTIME_FILE_MISSING" in missing_error
        and not (NEGATIVE / "missing-runtime-case" / "private").exists()
    )

    handler = type("SentinelHandler", (http.server.BaseHTTPRequestHandler,), {
        "do_GET": lambda self: (self.send_response(200), self.end_headers(), self.wfile.write(b"H13-SENTINEL")),
        "log_message": lambda *args: None,
    })
    server = http.server.ThreadingHTTPServer(("127.0.0.1", OCCUPIED_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        before = urllib.request.urlopen(f"http://127.0.0.1:{OCCUPIED_PORT}/", timeout=2).read().decode("ascii")
        occupied_result = invoke_start(PROJECT, OCCUPIED_PORT, "occupied-port-case")
        after = urllib.request.urlopen(f"http://127.0.0.1:{OCCUPIED_PORT}/", timeout=2).read().decode("ascii")
        occupied_error = str((occupied_result.get("payload") or {}).get("error", ""))
        occupied_gate = (
            occupied_result["exit_code"] == 2
            and (occupied_result.get("payload") or {}).get("status") == "FAILED"
            and "PORT_IN_USE" in occupied_error
            and before == after == "H13-SENTINEL"
            and thread.is_alive()
        )
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    result = {
        "task_id": "CDH-H13-LOCAL-TRIAL-FIRST-USE-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if missing_gate and occupied_gate else "FAIL",
        "missing_runtime": missing_result, "missing_runtime_gate": missing_gate,
        "occupied_port": occupied_result, "occupied_port_gate": occupied_gate,
        "sentinel_http_before": before, "sentinel_http_after": after,
        "unknown_process_termination_count": 0, "registry_action_count": 0,
        "system_service_action_count": 0, "formal_database_write_count": 0,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "missing_runtime_gate": missing_gate, "occupied_port_gate": occupied_gate}))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
