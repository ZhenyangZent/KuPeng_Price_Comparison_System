from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from preview_server import A10_SHA256, B11_SHA256, B15_SHA256, B16_SHA256, PreviewError, sha256_file, verify_pinned_release


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def append_event(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def project_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def request(port: int, method: str, path: str, *, token: str | None = None, timeout: float = 2.0) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["X-CDH-Control-Token"] = token
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        return response.status, json.loads(body.decode("utf-8")) if body else {}
    finally:
        connection.close()


def health(port: int) -> dict[str, object] | None:
    try:
        status, payload = request(port, "GET", "/__cdh/health", timeout=0.8)
        return payload if status == 200 and payload.get("status") == "READY" else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE if os.name == "nt" else socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def read_receipt(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return None


def verify_inputs(root: Path) -> dict[str, str]:
    a10 = root / "review" / "releases" / "CDH_A_R08_001_REVIEW.zip"
    b11 = root / "review" / "releases" / "CDH_B_R07_001_REVIEW.zip"
    b15 = root / "review" / "releases" / "CDH_B_R11_002_REVIEW.zip"
    b16 = root / "review" / "releases" / "CDH_B_R12_003_REVIEW.zip"
    verify_pinned_release(a10, A10_SHA256, "A10_R08")
    verify_pinned_release(b11, B11_SHA256, "B11_R07")
    verify_pinned_release(b15, B15_SHA256, "B15_R11_REV2")
    verify_pinned_release(b16, B16_SHA256, "B16_R12_REV3")
    return {"a10_r08_sha256": sha256_file(a10), "b11_r07_sha256": sha256_file(b11), "b15_r11_rev2_sha256": sha256_file(b15), "b16_r12_sha256": sha256_file(b16)}


def command_start(args: argparse.Namespace) -> int:
    root = args.project_root.resolve()
    state = args.state_dir.resolve()
    receipt_path, token_path = state / "active.json", state / "control.token"
    existing = read_receipt(receipt_path)
    if existing:
        running = health(int(existing.get("port", 0)))
        if running and running.get("instance_id") == existing.get("instance_id"):
            print(json.dumps({"status": "ALREADY_RUNNING", "url": existing["url"], "receipt": str(receipt_path)}, ensure_ascii=False))
            return 0
        raise PreviewError("STALE_RECEIPT_MANUAL_REVIEW: use stop after confirming the recorded instance")
    pinned = verify_inputs(root)
    if not port_free(args.port):
        raise PreviewError(f"PORT_IN_USE: 127.0.0.1:{args.port}")
    state.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(48)
    token_path.write_text(token + "\n", encoding="utf-8")
    instance_id = secrets.token_hex(16)
    log_dir = args.log_dir.resolve(); log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"preview-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{instance_id[:8]}.log"
    command = [sys.executable, str(Path(__file__).with_name("preview_server.py")), "--project-root", str(root), "--port", str(args.port), "--runtime-root", str(args.runtime_root.resolve()), "--token-file", str(token_path), "--instance-id", instance_id, "--private-data-root", str(args.private_data_root.resolve())]
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    with log_path.open("ab", buffering=0) as log:
        child = subprocess.Popen(command, cwd=Path(__file__).parent, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, close_fds=True)
    deadline = time.monotonic() + args.timeout
    ready = None
    while time.monotonic() < deadline:
        if child.poll() is not None:
            break
        ready = health(args.port)
        if ready and ready.get("instance_id") == instance_id:
            break
        time.sleep(0.1)
    if not ready or ready.get("instance_id") != instance_id:
        if child.poll() is None:
            child.terminate()
        token_path.unlink(missing_ok=True)
        detail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:] if log_path.exists() else ""
        raise PreviewError(f"STARTUP_FAILED: exit={child.poll()} log={log_path} detail={detail}")
    receipt = {"schema_version": "CDH-A11-LOCAL-PREVIEW-RECEIPT-1", "instance_id": instance_id, "pid": child.pid, "port": args.port, "url": f"http://127.0.0.1:{args.port}/?mode=synthetic&contract=v4", "started_at": utc_now(), "log": str(log_path), "control_token_sha256": hashlib.sha256(token.encode()).hexdigest(), **pinned}
    atomic_json(receipt_path, receipt)
    append_event(state / "history.jsonl", {"event": "START", **receipt})
    print(json.dumps({"status": "READY", "url": receipt["url"], "receipt": str(receipt_path), "log": str(log_path), **pinned}, ensure_ascii=False))
    return 0


def command_status(args: argparse.Namespace) -> int:
    receipt = read_receipt(args.state_dir.resolve() / "active.json")
    if not receipt:
        print(json.dumps({"status": "STOPPED"}))
        return 3
    current = health(int(receipt.get("port", 0)))
    if current and current.get("instance_id") == receipt.get("instance_id"):
        print(json.dumps({"status": "READY", "url": receipt.get("url"), "receipt": str(args.state_dir.resolve() / "active.json")}, ensure_ascii=False))
        return 0
    print(json.dumps({"status": "STALE_RECEIPT_MANUAL_REVIEW", "receipt": str(args.state_dir.resolve() / "active.json")}, ensure_ascii=False))
    return 4


def command_stop(args: argparse.Namespace) -> int:
    state = args.state_dir.resolve(); receipt_path, token_path = state / "active.json", state / "control.token"
    receipt = read_receipt(receipt_path)
    if not receipt:
        print(json.dumps({"status": "ALREADY_STOPPED"}))
        return 0
    token = token_path.read_text(encoding="utf-8").strip() if token_path.is_file() else ""
    if not token or hashlib.sha256(token.encode()).hexdigest() != receipt.get("control_token_sha256"):
        raise PreviewError("CONTROL_RECEIPT_MISMATCH_MANUAL_REVIEW")
    current = health(int(receipt["port"]))
    if not current or current.get("instance_id") != receipt.get("instance_id"):
        raise PreviewError("PROCESS_IDENTITY_MISMATCH_MANUAL_REVIEW")
    status, payload = request(int(receipt["port"]), "POST", "/__cdh/shutdown", token=token)
    if status != 202 or payload.get("instance_id") != receipt.get("instance_id"):
        raise PreviewError(f"STOP_REJECTED: status={status} payload={payload}")
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline and health(int(receipt["port"])) is not None:
        time.sleep(0.1)
    if health(int(receipt["port"])) is not None:
        raise PreviewError("STOP_TIMEOUT_MANUAL_REVIEW")
    append_event(state / "history.jsonl", {"event": "STOP", "instance_id": receipt["instance_id"], "port": receipt["port"], "stopped_at": utc_now()})
    stopped = state / f"stopped-{receipt['instance_id']}.json"
    os.replace(receipt_path, stopped)
    token_path.unlink(missing_ok=True)
    print(json.dumps({"status": "STOPPED", "instance_id": receipt["instance_id"], "receipt": str(stopped)}, ensure_ascii=False))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = project_root_from_script()
    parser = argparse.ArgumentParser(description="Start, inspect, or stop the CDH A11 local preview")
    parser.add_argument("action", choices=("start", "status", "stop"))
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--state-dir", type=Path, default=root / "apps" / "price-web" / "local-preview-a11" / "state")
    parser.add_argument("--runtime-root", type=Path, default=root / "apps" / "price-web" / "local-preview-a11" / "runtime")
    parser.add_argument("--log-dir", type=Path, default=root / "logs" / "A11")
    parser.add_argument("--private-data-root", type=Path, default=root / "data" / "private_user_observations_b15")
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.action == "start":
        return command_start(args)
    if args.action == "status":
        return command_status(args)
    return command_stop(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreviewError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc), "at": utc_now()}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
