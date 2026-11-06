from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "review" / "releases" / "CDH_A_R12_001_REVIEW.zip"
EXPECTED_SHA256 = "5cc44dedd910ff9b2055cfc2772ad0c3d6db627ffc818794f81fd3d9b5552d4b"
EXPECTED_B16_SHA256 = "d2149952fe1693381f74ac639a770b393b8703a368df68eea990cd5e231cf23b"
PREFIX = "CDH_A_R12_001_REVIEW/"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe(name: str) -> bool:
    value = PurePosixPath(name)
    return bool(name) and not value.is_absolute() and ".." not in value.parts and "\\" not in name and "\x00" not in name


def required(text: str, values: tuple[str, ...], label: str) -> dict[str, object]:
    missing = [value for value in values if value not in text]
    return {"label": label, "gate": "PASS" if not missing else "FAIL", "missing": missing}


def main() -> int:
    checks: list[dict[str, object]] = []
    archive_hash = file_sha256(ARCHIVE)
    with zipfile.ZipFile(ARCHIVE) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        crc_bad = archive.testzip()
        unsafe = [name for name in names if not safe(name)]
        duplicate_count = len(names) - len(set(names))
        case_duplicate_count = len(names) - len({name.casefold() for name in names})
        links = [item.filename for item in infos if ((item.external_attr >> 16) & 0o170000) == 0o120000]
        manifest_name = PREFIX + "SHA256_MANIFEST.json"
        manifest_raw = archive.read(manifest_name)
        manifest = json.loads(manifest_raw)
        declared = {PREFIX + item["path"]: item for item in manifest["payloads"]}
        actual = set(names) - {manifest_name}
        missing = sorted(set(declared) - actual)
        undeclared = sorted(actual - set(declared))
        mismatched = []
        for name, item in declared.items():
            if name not in actual:
                continue
            data = archive.read(name)
            if len(data) != item["bytes"] or sha256(data) != item["sha256"]:
                mismatched.append(name)
        embedded_b16 = archive.read(PREFIX + "dependencies/CDH_B_R12_001_REVIEW.zip")
        client = archive.read(PREFIX + "apps/price-web/frontend/src/batchImportClient.ts").decode("utf-8")
        preview = archive.read(PREFIX + "apps/price-web/frontend/src/batchImportPreview.ts").decode("utf-8")
        server = archive.read(PREFIX + "apps/price-web/local-preview-a11/preview_server.py").decode("utf-8")
        integration_test = archive.read(PREFIX + "apps/price-web/frontend/tests/a15_b16_integration.test.tsx").decode("utf-8")
        e2e = json.loads(archive.read(PREFIX + "reports/A15_FINAL/logs/A15_ACTUAL_CHROME_E2E.json"))
        input_dependency = json.loads(archive.read(PREFIX + "INPUT_DEPENDENCY.json"))
        checks.extend(
            [
                required(client, (
                    '"/api/private-observations/v1/session"',
                    '"/api/private-observations/v1/batch-preview"',
                    '"/api/private-observations/v1/batch-confirm"',
                    '"X-CDH-CSRF-Token"',
                    'content_base64: bytesToBase64(bytes)',
                    'explicit_confirm: true',
                    'result.status === 200 || result.status === 422',
                    'result.status === 200 || result.status === 201',
                    'credentials: "omit"',
                    'redirect: "error"',
                ), "A15_CLIENT_WIRE"),
                required(preview, (
                    "A15_PREFLIGHT_MAX_BYTES = 1024 * 1024",
                    "A15_PREFLIGHT_MAX_ROWS = 500",
                    'schema_version !== "CDH-B16-BATCH-FILE-1"',
                    "JSON_DUPLICATE_KEY",
                    "CSV_HEADER_CONTRACT_MISMATCH",
                    "B16_SERVER_VALIDATION_REQUIRED",
                ), "A15_PREFLIGHT"),
                required(server, (
                    f'B16_SHA256 = "{EXPECTED_B16_SHA256}"',
                    'allowed_origins = (f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}")',
                    'request_limit = 1_500_000 if path == "/api/private-observations/v1/batch-preview"',
                    '16 * 1024 if path == "/api/private-observations/v1/batch-confirm"',
                    'headers = {"Host": "127.0.0.1", "Accept": "application/json"}',
                ), "A15_LOOPBACK_PROXY"),
                required(integration_test, (
                    "database_write_count = 0",
                    "明確確認並保存",
                    "HTTP 201",
                    "冪等重播，沒有新增資料",
                    "逐筆驗證失敗，禁止確認",
                    "confirmed_after_coupon_price_twd: 800",
                    "platform_verified: true",
                ), "A15_INTEGRATION_TEST_SCOPE"),
            ]
        )
    http_trace = e2e.get("stdout", "")
    result = {
        "schema_version": "CDH-D13-A15-BOUNDARY-PRECHECK-1",
        "task_id": "CDH-D13-B16-BATCH-IMPORT-SECURITY",
        "a15": {
            "filename": ARCHIVE.name,
            "sha256": archive_hash,
            "expected_sha256": EXPECTED_SHA256,
            "sha256_gate": "PASS" if archive_hash == EXPECTED_SHA256 else "FAIL",
            "crc_gate": "PASS" if crc_bad is None else "FAIL",
            "manifest_sha256": sha256(manifest_raw),
            "manifest_schema": manifest.get("schema_version"),
            "manifest_payload_count": len(declared),
            "missing": len(missing),
            "mismatch": len(mismatched),
            "undeclared": len(undeclared),
            "unsafe_paths": len(unsafe),
            "duplicates": duplicate_count,
            "case_duplicates": case_duplicate_count,
            "links": len(links),
        },
        "embedded_b16": {
            "sha256": sha256(embedded_b16),
            "expected_sha256": EXPECTED_B16_SHA256,
            "gate": "PASS" if sha256(embedded_b16) == EXPECTED_B16_SHA256 else "FAIL",
        },
        "input_dependency_b16_sha256": input_dependency["inputs"]["B16_R12"]["sha256"],
        "static_checks": checks,
        "a15_evidence": {
            "declared_pass": e2e.get("pass"),
            "declared_exit_code": e2e.get("exit_code"),
            "actual_b16_http_trace_present": "ACTUAL_A15_UI_TO_B16_R12_LOCAL_API" in http_trace,
            "http_422_present": '"status":422' in http_trace,
            "http_201_present": '"status":201' in http_trace,
            "http_200_replay_present": '"status":200' in http_trace,
            "database_unchanged_by_read_present": '"database_unchanged_by_read":true' in http_trace,
        },
        "b16_rev2_gate": "NOT_RUN_INPUT_UNAVAILABLE",
    }
    flat_failures = [
        result["a15"][key]
        for key in ("sha256_gate", "crc_gate")
        if result["a15"][key] != "PASS"
    ]
    flat_failures.extend(
        "FAIL"
        for key in ("missing", "mismatch", "undeclared", "unsafe_paths", "duplicates", "case_duplicates", "links")
        if result["a15"][key] != 0
    )
    if result["embedded_b16"]["gate"] != "PASS" or any(item["gate"] != "PASS" for item in checks):
        flat_failures.append("FAIL")
    evidence_gate = (
        result["a15_evidence"]["declared_pass"] is True
        and result["a15_evidence"]["declared_exit_code"] == 0
        and all(
            result["a15_evidence"][key] is True
            for key in (
                "actual_b16_http_trace_present",
                "http_422_present",
                "http_201_present",
                "http_200_replay_present",
                "database_unchanged_by_read_present",
            )
        )
    )
    if not evidence_gate:
        flat_failures.append("FAIL")
    result["a15_to_b16_rev1_boundary_gate"] = "PASS" if not flat_failures else "FAIL"
    out = ROOT / "review" / "D13" / "002" / "precheck" / "A15_BOUNDARY_PRECHECK.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["a15_to_b16_rev1_boundary_gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
