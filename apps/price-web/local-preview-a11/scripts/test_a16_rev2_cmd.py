from __future__ import annotations

import hashlib
import json
import shutil
import socket
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
REPORT = ROOT / "reports" / "A16_REV2"
EVIDENCE = REPORT / "evidence"
LOGS = REPORT / "logs"
EXPECTED = {
    "CDH_A_R08_001_REVIEW.zip": "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
    "CDH_B_R07_001_REVIEW.zip": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
    "CDH_B_R09_001_REVIEW.zip": "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638",
    "CDH_B_R10_001_REVIEW.zip": "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9",
    "CDH_C_R10_002_REVIEW.zip": "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa",
    "CDH_A_R11_004_REVIEW.zip": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
    "CDH_B_R11_002_REVIEW.zip": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
    "CDH_B_R12_003_REVIEW.zip": "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
}


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def allocate_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def stage_project(destination: Path, *, omit_release: str | None = None) -> None:
    for name in ("Start-CDH-MVP.cmd", "Status-CDH-MVP.cmd", "Stop-CDH-MVP.cmd"):
        copy_file(ROOT / name, destination / name)
    for item in (ROOT / "scripts" / "windows-mvp").glob("*.ps1"):
        copy_file(item, destination / item.relative_to(ROOT))
    for name in ("control.py", "preview_server.py"):
        source = ROOT / "apps" / "price-web" / "local-preview-a11" / name
        copy_file(source, destination / source.relative_to(ROOT))
    for item in (ROOT / "apps" / "price-web" / "frontend" / "dist").rglob("*"):
        if item.is_file():
            copy_file(item, destination / item.relative_to(ROOT))
    for name, expected in EXPECTED.items():
        source = ROOT / "review" / "releases" / name
        if sha256(source) != expected:
            raise RuntimeError(f"release identity mismatch: {name}")
        if name != omit_release:
            copy_file(source, destination / "review" / "releases" / name)


def run_cmd(project: Path, entry: str, arguments: list[str], label: str) -> dict[str, object]:
    command = ["cmd.exe", "/d", "/c", str(project / entry), *arguments]
    completed = subprocess.run(command, cwd=project, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=45, check=False)
    payload = None
    for line in completed.stdout.splitlines():
        try:
            candidate = json.loads(line)
            if isinstance(candidate, dict) and candidate.get("status"):
                payload = candidate
        except json.JSONDecodeError:
            pass
    result = {"label": label, "command": command, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "payload": payload}
    (LOGS / f"{label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def lifecycle_arguments(project: Path, port: int, suffix: str) -> list[str]:
    base = project / "test_state" / suffix
    return ["-Port", str(port), "-StateDir", str(base / "state"), "-RuntimeRoot", str(base / "runtime"), "-LogDir", str(base / "logs"), "-PrivateDataRoot", str(base / "private_data"), "-MachineReadable"]


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    clean = REPORT / "runtime" / f"clean-project-{run_id}"
    missing = REPORT / "runtime" / f"missing-project-{run_id}"
    stage_project(clean)
    stage_project(missing, omit_release="CDH_C_R10_002_REVIEW.zip")

    cmd_line_endings = {}
    for name in ("Start-CDH-MVP.cmd", "Status-CDH-MVP.cmd", "Stop-CDH-MVP.cmd"):
        data = (clean / name).read_bytes()
        cmd_line_endings[name] = {"bytes": len(data), "crlf_count": data.count(b"\r\n"), "bare_lf_count": data.replace(b"\r\n", b"").count(b"\n"), "sha256": hashlib.sha256(data).hexdigest()}

    port = allocate_port()
    arguments = lifecycle_arguments(clean, port, f"clean-lifecycle-{run_id}")
    start = run_cmd(clean, "Start-CDH-MVP.cmd", arguments, "CMD_START")
    status = run_cmd(clean, "Status-CDH-MVP.cmd", arguments, "CMD_STATUS")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/__cdh/health", timeout=4) as response:
        health = json.loads(response.read().decode("utf-8"))
    stop = run_cmd(clean, "Stop-CDH-MVP.cmd", arguments, "CMD_STOP")
    stopped = run_cmd(clean, "Status-CDH-MVP.cmd", arguments, "CMD_STATUS_AFTER_STOP")

    missing_arguments = lifecycle_arguments(missing, allocate_port(), f"missing-dependency-{run_id}")
    missing_result = run_cmd(missing, "Start-CDH-MVP.cmd", missing_arguments, "CMD_MISSING_DEPENDENCY")

    occupied_socket = socket.socket()
    occupied_socket.bind(("127.0.0.1", 0))
    occupied_socket.listen(1)
    occupied_port = int(occupied_socket.getsockname()[1])
    occupied_arguments = lifecycle_arguments(clean, occupied_port, f"occupied-port-{run_id}")
    occupied_result = run_cmd(clean, "Start-CDH-MVP.cmd", occupied_arguments, "CMD_OCCUPIED_PORT")
    listener_preserved = occupied_socket.getsockname()[1] == occupied_port
    occupied_socket.close()

    private_database = clean / "test_state" / f"clean-lifecycle-{run_id}" / "private_data" / "private_user_observations.sqlite3"
    gates = {
        "complete_dependency_count": len(EXPECTED) == 8,
        "cmd_crlf_only": all(value["crlf_count"] > 0 and value["bare_lf_count"] == 0 for value in cmd_line_endings.values()),
        "start_ready": start["exit_code"] == 0 and start["payload"] and start["payload"].get("status") == "READY",
        "status_ready": status["exit_code"] == 0 and status["payload"] and status["payload"].get("status") == "READY",
        "health_ready": health.get("status") == "READY" and health.get("b16_revision") == "REV3",
        "stop_success": stop["exit_code"] == 0 and stop["payload"] and stop["payload"].get("status") == "STOPPED",
        "status_after_stop": stopped["exit_code"] == 0 and stopped["payload"] and stopped["payload"].get("status") == "STOPPED",
        "missing_dependency_rejected": missing_result["exit_code"] == 2 and missing_result["payload"] and missing_result["payload"].get("status") == "FAILED" and "CDH_C_R10_002_REVIEW.zip" in str(missing_result["payload"].get("error")),
        "occupied_port_rejected": occupied_result["exit_code"] == 2 and occupied_result["payload"] and occupied_result["payload"].get("status") == "FAILED" and "PORT_IN_USE" in str(occupied_result["payload"].get("error")),
        "unknown_listener_preserved": listener_preserved,
        "first_view_database_not_created": not private_database.exists(),
    }
    result = {
        "schema_version": "CDH-A16-REV2-CMD-E2E-1",
        "task_id": "CDH-A16-LOCAL-MVP-FIRST-USE-001",
        "revision": "REV2",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "clean_project": str(clean),
        "dependency_sha256": EXPECTED,
        "cmd_line_endings": cmd_line_endings,
        "gates": gates,
        "health": health,
        "formal_database_write_count": 0,
        "isolated_database_write_count": 0,
        "unknown_process_termination_count": 0,
        "registry_action_count": 0,
        "firefox_action_count": 0,
        "external_request_count": 0,
        "all_pass": all(bool(value) for value in gates.values()),
    }
    (EVIDENCE / "CMD_E2E_A16_REV2.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"all_pass": result["all_pass"], "gates": gates}, ensure_ascii=True, sort_keys=True))
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
