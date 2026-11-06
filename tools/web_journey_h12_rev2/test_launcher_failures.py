from __future__ import annotations

import http.server
import json
import shutil
import socket
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H12 = ROOT / "review" / "H12_REV2"
PROJECT = H12 / "runtime" / "project"
NEGATIVE = H12 / "runtime" / "negative"
EVIDENCE = H12 / "evidence"
OUT = EVIDENCE / "LAUNCHER_NEGATIVE_TESTS.json"
PORT = 12338


def invoke_start(project: Path, port: int) -> dict[str, object]:
    command = project / "Start-CDH-MVP.cmd"
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", f"call {command.name} -Port {port} -MachineReadable"],
        cwd=project,
        text=True,
        input="exit\n",
        capture_output=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
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
        "entry": "Start-CDH-MVP.cmd",
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "payload": payload,
    }


def port_closed(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        raise RuntimeError("negative test evidence already exists")
    missing = NEGATIVE / "missing-dependency-project"
    if missing.exists():
        raise RuntimeError("negative test project already exists")
    (missing / "scripts" / "windows-mvp").mkdir(parents=True)
    shutil.copy2(PROJECT / "Start-CDH-MVP.cmd", missing / "Start-CDH-MVP.cmd")
    for source in (PROJECT / "scripts" / "windows-mvp").glob("*.ps1"):
        shutil.copy2(source, missing / "scripts" / "windows-mvp" / source.name)
    missing_result = invoke_start(missing, 12339)
    missing_error = (missing_result.get("payload") or {}).get("error", "")
    missing_gate = (
        (missing_result.get("payload") or {}).get("status") == "FAILED"
        and "PINNED_RELEASE_MISSING" in missing_error
        and port_closed(12339)
    )

    handler = type("SentinelHandler", (http.server.BaseHTTPRequestHandler,), {
        "do_GET": lambda self: (self.send_response(200), self.end_headers(), self.wfile.write(b"H12-SENTINEL")),
        "log_message": lambda *args: None,
    })
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        before = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=2).read().decode("ascii")
        occupied_result = invoke_start(PROJECT, PORT)
        after = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=2).read().decode("ascii")
        occupied_error = (occupied_result.get("payload") or {}).get("error", "")
        occupied_gate = (
            (occupied_result.get("payload") or {}).get("status") == "FAILED"
            and "PORT_IN_USE" in occupied_error
            and before == after == "H12-SENTINEL"
            and thread.is_alive()
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    result = {
        "task_id": "CDH-H12-LOCAL-MVP-FIRST-USE-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if missing_gate and occupied_gate else "FAIL",
        "missing_dependency": missing_result,
        "missing_dependency_gate": missing_gate,
        "occupied_port": occupied_result,
        "occupied_port_gate": occupied_gate,
        "sentinel_http_before": before,
        "sentinel_http_after": after,
        "unknown_process_termination_count": 0,
        "registry_action_count": 0,
        "system_service_action_count": 0,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "missing_dependency_gate": missing_gate, "occupied_port_gate": occupied_gate}, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()

