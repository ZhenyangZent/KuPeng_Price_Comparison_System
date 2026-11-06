from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


EXPECTED = {
    "CDH_A_R08_001_REVIEW.zip": "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
    "CDH_B_R07_001_REVIEW.zip": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
    "CDH_B_R10_001_REVIEW.zip": "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9",
    "CDH_C_R10_002_REVIEW.zip": "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa",
    "CDH_B_R11_002_REVIEW.zip": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0)); return int(probe.getsockname()[1])


def reader(stream, lines: list[str], events: queue.Queue[str]) -> None:
    for line in iter(stream.readline, ""):
        lines.append(line.rstrip("\r\n")); events.put(line)


def python_health(port: int) -> dict:
    started = time.monotonic(); connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", "/__cdh/health", headers={"Host": f"127.0.0.1:{port}"}); response = connection.getresponse(); body = response.read().decode("utf-8", errors="replace")
        return {"status": response.status, "body": json.loads(body), "duration_seconds": round(time.monotonic() - started, 6)}
    except Exception as exc: return {"status": None, "error": f"{type(exc).__name__}: {exc}", "duration_seconds": round(time.monotonic() - started, 6)}
    finally: connection.close()


def listener_readback(port: int) -> dict:
    completed = subprocess.run(["netstat", "-ano", "-p", "TCP"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
    pattern = re.compile(rf"^\s*TCP\s+127\.0\.0\.1:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$", re.MULTILINE)
    pids = [int(value) for value in pattern.findall(completed.stdout)]
    return {"return_code": completed.returncode, "listener_count": len(pids), "pids": pids, "stderr": completed.stderr}


def node_health(node: str, url: str) -> dict:
    code = "fetch(process.argv[1]).then(async r=>{console.log(JSON.stringify({status:r.status,body:await r.json()}));process.exit(r.ok?0:2)}).catch(e=>{console.error(e.stack||String(e));process.exit(3)})"
    try:
        completed = subprocess.run([node, "-e", code, url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=10, shell=False, check=False)
        parsed = json.loads(completed.stdout) if completed.returncode == 0 else None
        return {"return_code": completed.returncode, "result": parsed, "stdout": completed.stdout, "stderr": completed.stderr}
    except subprocess.TimeoutExpired as exc: return {"return_code": None, "error": "TIMEOUT", "stdout": exc.stdout, "stderr": exc.stderr}


def chrome_health(chrome: str, url: str, profile: Path) -> dict:
    command = [chrome, "--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", f"--user-data-dir={profile}", "--dump-dom", url]
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=15, shell=False, check=False)
        health_visible = '"status": "READY"' in completed.stdout or '"status":"READY"' in completed.stdout
        return {"return_code": completed.returncode, "health_visible": health_visible, "stdout": completed.stdout, "stderr": completed.stderr}
    except subprocess.TimeoutExpired as exc: return {"return_code": None, "health_visible": False, "error": "TIMEOUT", "stdout": exc.stdout, "stderr": exc.stderr}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--project", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--mode", required=True); parser.add_argument("--python", required=True); parser.add_argument("--node", default="node"); parser.add_argument("--chrome", required=True); args = parser.parse_args()
    project, output = args.project.resolve(), args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    releases = project / "review" / "releases"; release_hashes = {name: sha256(releases / name) for name in EXPECTED}; release_gate = release_hashes == EXPECTED
    preview = project / "apps" / "price-web" / "local-preview-a11" / "preview_server.py"; work = output.parent / f"runtime-{args.mode}"; runtime = work / "server"; private = project / "review" / "G10_DIAGNOSTIC" / args.mode / "private-data"; state = work / "state"; profile = work / "chrome-profile"
    for directory in (runtime, private, state): directory.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(48); token_path = state / "control.token"; token_path.write_text(token + "\n", encoding="utf-8"); instance = secrets.token_hex(16); port = free_port()
    command = [args.python, str(preview), "--project-root", str(project), "--port", str(port), "--runtime-root", str(runtime), "--token-file", str(token_path), "--instance-id", instance, "--private-data-root", str(private)]
    env = {**os.environ, "PYTHONUTF8": "1", "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": ""}
    child = subprocess.Popen(command, cwd=preview.parent, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", shell=False)
    stdout: list[str] = []; stderr: list[str] = []; events: queue.Queue[str] = queue.Queue(); threads = [threading.Thread(target=reader, args=(child.stdout, stdout, events), daemon=True), threading.Thread(target=reader, args=(child.stderr, stderr, events), daemon=True)]
    for thread in threads: thread.start()
    ready_line = None; deadline = time.monotonic() + 30
    while time.monotonic() < deadline and child.poll() is None:
        try: line = events.get(timeout=0.1)
        except queue.Empty: continue
        try: value = json.loads(line)
        except json.JSONDecodeError: continue
        if value.get("status") == "READY": ready_line = value; break
    alive_after_ready = child.poll() is None; time.sleep(0.25); listener = listener_readback(port); python_result = python_health(port); node_result = node_health(args.node, f"http://127.0.0.1:{port}/__cdh/health"); chrome_result = chrome_health(args.chrome, f"http://127.0.0.1:{port}/__cdh/health", profile); alive_after_probes = child.poll() is None
    shutdown = None
    if python_result.get("status") == 200:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request("POST", "/__cdh/shutdown", headers={"Host": f"127.0.0.1:{port}", "X-CDH-Control-Token": token}); response = connection.getresponse(); shutdown = {"status": response.status, "body": response.read().decode("utf-8", errors="replace")}
        except Exception as exc: shutdown = {"status": None, "error": f"{type(exc).__name__}: {exc}"}
        finally: connection.close()
    if child.poll() is None:
        try: child.wait(timeout=8)
        except subprocess.TimeoutExpired: child.terminate()
    if child.poll() is None:
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
    for thread in threads: thread.join(timeout=1)
    database = private / "private_user_observations.sqlite3"
    payload = {"schema_version": "CDH-G10-H10-LOOPBACK-DIAGNOSTIC-1", "created_at_utc": datetime.now(timezone.utc).isoformat(), "mode": args.mode, "project": str(project), "exact_release_gate": release_gate, "release_hashes": release_hashes, "server_command": command, "port": port, "child_pid": child.pid, "ready_line": ready_line, "alive_after_ready": alive_after_ready, "listener": listener, "python_http": python_result, "node_fetch": node_result, "chrome_dump_dom": chrome_result, "alive_after_probes": alive_after_probes, "shutdown": shutdown, "child_exit_code": child.returncode, "stdout": stdout, "stderr": stderr, "database_created": database.exists(), "database_sha256": sha256(database) if database.exists() else None}
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"mode": args.mode, "ready": ready_line is not None, "alive": alive_after_ready, "listener_count": listener["listener_count"], "python_status": python_result.get("status"), "node_exit": node_result.get("return_code"), "chrome_health": chrome_result.get("health_visible"), "child_exit": child.returncode}))
    return 0


if __name__ == "__main__": raise SystemExit(main())
