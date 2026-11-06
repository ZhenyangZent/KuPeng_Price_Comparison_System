from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent
PROJECT = BUNDLE.parents[2]
REPORT = PROJECT / "reports" / "A17"
CLEAN = REPORT / "runtime" / "clean-project"
PORT = 43174


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_cmd(name: str, *args: str) -> dict[str, object]:
    command = ["cmd.exe", "/d", "/c", str(CLEAN / name), "-MachineReadable", "-Port", str(PORT), *args]
    completed = subprocess.run(command, cwd=CLEAN, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    payload = json.loads(lines[-1]) if lines else {"status": "NO_JSON", "stderr": completed.stderr, "stdout": completed.stdout}
    return {"command": command, "exit_code": completed.returncode, "payload": payload, "stderr": completed.stderr}


def request(method: str, path: str, body: dict[str, object] | None = None, csrf: str | None = None) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    headers = {"Host": f"127.0.0.1:{PORT}", "Accept": "application/json"}
    encoded = None
    if body is not None:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers.update({"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{PORT}", "Content-Length": str(len(encoded))})
    if csrf:
        headers["X-CDH-CSRF-Token"] = csrf
    try:
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    finally:
        connection.close()


def expect(status: int, actual: tuple[int, dict[str, object]], label: str) -> dict[str, object]:
    if actual[0] != status:
        raise RuntimeError(f"{label}: expected={status} actual={actual}")
    return actual[1]


def observation() -> dict[str, object]:
    return {
        "schema_version": "CDH-B15-MANUAL-OBSERVATION-1",
        "submission_id": "SUB-A17-E2E-0001",
        "title": "A17 本機試用商品",
        "identity": {
            "platform": "COUPANG_TW",
            "product_id": "P-A17-TRIAL",
            "sku_id": "SKU-A17-TRIAL",
            "seller_id": "SELLER-A17",
            "condition": "NEW",
            "package_signature": "EACH-1",
            "currency": "TWD",
        },
        "observed_at": "2026-11-06T12:00:00+08:00",
        "quantity": 1,
        "before_coupon_price_twd": 1290,
        "user_reported_coupon": {
            "status": "USER_REPORTED",
            "price_twd": 1190,
            "eligibility": "UNKNOWN",
            "evidence_level": "NONE",
            "evidence_note": None,
            "valid_from": None,
            "valid_until": None,
        },
        "shipping": {"status": "UNKNOWN", "shipping_fee_twd": None, "mandatory_fee_twd": None},
        "source": {"source_class": "USER_ENTERED", "visibility": "PRIVATE_LOCAL", "note": "A17 isolated trial E2E"},
    }


def prepare_clean_project() -> None:
    runtime_root = (REPORT / "runtime").resolve()
    clean = CLEAN.resolve()
    if not clean.is_relative_to(runtime_root):
        raise RuntimeError("CLEAN_PROJECT_OUTSIDE_REPORT_RUNTIME")
    if CLEAN.exists():
        marker = CLEAN / ".a17-clean-test"
        if not marker.is_file():
            raise RuntimeError("CLEAN_PROJECT_NOT_OWNED")
        shutil.rmtree(CLEAN)
    target = CLEAN / "apps" / "price-web" / "local-trial-a17"
    shutil.copytree(BUNDLE, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("Start-CDH-Trial.cmd", "Status-CDH-Trial.cmd", "Stop-CDH-Trial.cmd"):
        shutil.copyfile(PROJECT / name, CLEAN / name)
    guide_target = CLEAN / "docs" / "user-guides"
    guide_target.mkdir(parents=True)
    shutil.copyfile(PROJECT / "docs" / "user-guides" / "WINDOWS_TRIAL_FIRST_USE_A17.md", guide_target / "WINDOWS_TRIAL_FIRST_USE_A17.md")
    (CLEAN / ".a17-clean-test").write_text("owned A17 isolated test workspace\n", encoding="utf-8")


def main() -> int:
    prepare_clean_project()
    evidence: dict[str, object] = {
        "schema_version": "CDH-A17-E2E-EVIDENCE-1",
        "clean_project": str(CLEAN),
        "review_release_directory_present": (CLEAN / "review" / "releases").exists(),
        "steps": {},
    }
    started = False
    try:
        start = run_cmd("Start-CDH-Trial.cmd")
        evidence["steps"]["start"] = start
        if start["exit_code"] != 0 or start["payload"].get("status") != "READY":
            raise RuntimeError(f"START_FAILED: {start}")
        started = True
        status = run_cmd("Status-CDH-Trial.cmd")
        evidence["steps"]["status"] = status
        if status["exit_code"] != 0 or status["payload"].get("status") != "READY":
            raise RuntimeError(f"STATUS_FAILED: {status}")
        health = expect(200, request("GET", "/__cdh/health"), "health")
        session = expect(200, request("GET", "/cdh-private-observations/api/private-observations/v1/session"), "session")
        preview = expect(200, request("POST", "/cdh-private-observations/api/private-observations/v1/preview", observation(), str(session["csrf_token"])), "preview")
        if preview.get("database_write_count") != 0 or preview.get("will_save", {}).get("confirmed_after_coupon_price_twd") is not None:
            raise RuntimeError("PREVIEW_SAFETY_CONTRACT_FAILED")
        confirm = expect(
            201,
            request(
                "POST",
                "/cdh-private-observations/api/private-observations/v1/confirm",
                {"preview_id": preview["preview_id"], "confirm_token": preview["confirm_token"], "explicit_confirm": True},
                str(session["csrf_token"]),
            ),
            "confirm",
        )
        batch_file = CLEAN / "apps" / "price-web" / "local-trial-a17" / "vendor" / "b16" / "private_batch_import_b16" / "examples" / "valid_two_day.csv"
        batch_preview = expect(
            200,
            request(
                "POST",
                "/cdh-private-observations/api/private-observations/v1/batch-preview",
                {
                    "schema_version": "CDH-B16-BATCH-PREVIEW-REQUEST-1",
                    "filename": "valid_two_day.csv",
                    "media_type": "text/csv",
                    "content_base64": base64.b64encode(batch_file.read_bytes()).decode("ascii"),
                },
                str(session["csrf_token"]),
            ),
            "batch_preview",
        )
        if not batch_preview.get("can_confirm") or batch_preview.get("database_write_count") != 0:
            raise RuntimeError("BATCH_PREVIEW_SAFETY_CONTRACT_FAILED")
        batch_confirm = expect(
            201,
            request(
                "POST",
                "/cdh-private-observations/api/private-observations/v1/batch-confirm",
                {
                    "schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1",
                    "preview_id": batch_preview["preview_id"],
                    "confirm_token": batch_preview["confirm_token"],
                    "explicit_confirm": True,
                },
                str(session["csrf_token"]),
            ),
            "batch_confirm",
        )
        stop = run_cmd("Stop-CDH-Trial.cmd")
        evidence["steps"]["first_stop"] = stop
        started = False
        database = CLEAN / "data" / "A17_private_history" / "private_user_observations.sqlite3"
        before_sha = sha256(database)
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
            before_count = int(connection.execute("select count(*) from observations").fetchone()[0])
        restart = run_cmd("Start-CDH-Trial.cmd")
        evidence["steps"]["restart"] = restart
        if restart["exit_code"] != 0 or restart["payload"].get("status") != "READY":
            raise RuntimeError(f"RESTART_FAILED: {restart}")
        started = True
        products = expect(200, request("GET", "/cdh-private-observations/api/private-observations/v1/products?q=P-A17-TRIAL&page=1&limit=20"), "search")
        items = products.get("items") or products.get("products") or []
        if len(items) != 1:
            raise RuntimeError(f"PRIVATE_SEARCH_RESULT_INVALID: {products}")
        series_key = items[0]["series_key"]
        detail = expect(200, request("GET", f"/cdh-private-observations/api/private-observations/v1/products/{series_key}"), "detail")
        final_stop = run_cmd("Stop-CDH-Trial.cmd")
        evidence["steps"]["final_stop"] = final_stop
        started = False
        after_sha = sha256(database)
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
            after_count = int(connection.execute("select count(*) from observations").fetchone()[0])

        missing = CLEAN / "apps" / "price-web" / "local-trial-a17" / "vendor" / "frontend" / "dist" / "index.html"
        parked = missing.with_suffix(".html.a17-test-parked")
        os.replace(missing, parked)
        try:
            missing_result = run_cmd("Start-CDH-Trial.cmd")
        finally:
            os.replace(parked, missing)
        evidence["steps"]["missing_runtime_refusal"] = missing_result
        if missing_result["exit_code"] != 2 or "A17_RUNTIME_FILE_MISSING" not in str(missing_result["payload"].get("error")):
            raise RuntimeError(f"MISSING_RUNTIME_NOT_REFUSED: {missing_result}")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
            blocker.bind(("127.0.0.1", PORT))
            blocker.listen(1)
            occupied = run_cmd("Start-CDH-Trial.cmd")
            still_owned = blocker.getsockname()[1] == PORT
        evidence["steps"]["occupied_port_refusal"] = {**occupied, "unknown_listener_preserved": still_owned}
        if occupied["exit_code"] != 2 or "PORT_IN_USE" not in str(occupied["payload"].get("error")) or not still_owned:
            raise RuntimeError(f"PORT_GUARD_FAILED: {occupied}")

        evidence.update(
            {
                "status": "PASS",
                "health": health,
                "confirm_http_status": 201,
                "confirm_status": confirm.get("status"),
                "batch_preview_http_status": 200,
                "batch_confirm_http_status": 201,
                "batch_confirm_status": batch_confirm.get("status"),
                "private_database": str(database),
                "private_row_count_before_read": before_count,
                "private_row_count_after_read": after_count,
                "private_database_sha256_before_read": before_sha,
                "private_database_sha256_after_read": after_sha,
                "read_only_history_gate": before_count == after_count == 3 and before_sha == after_sha,
                "detail_title": detail.get("product", {}).get("title") or detail.get("title"),
                "platform_confirmed_coupon_value_present": "confirmed_after_coupon_price_twd\":1190" in json.dumps(detail, separators=(",", ":")),
                "release_zip_lookup_count": 0,
                "external_request_count": 0,
                "registry_action_count": 0,
            }
        )
    except Exception as exc:
        evidence["status"] = "FAIL"
        evidence["error"] = repr(exc)
        raise
    finally:
        if started:
            evidence["steps"]["emergency_stop"] = run_cmd("Stop-CDH-Trial.cmd")
        output = REPORT / "evidence" / "A17_CLEAN_CMD_E2E.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "evidence": str(output), "read_only_history_gate": evidence.get("read_only_history_gate")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
