from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[4]
A14 = "--a14" in sys.argv
A13_REV3 = "--a13-rev3" in sys.argv
A13_REV2 = "--a13-rev2" in sys.argv and not A13_REV3
A13 = ("--a13" in sys.argv or A13_REV2 or A13_REV3) and not A14
A12 = "--a12" in sys.argv and not A13
TASK_ID = "CDH-A14-PRIVATE-HISTORY-BROWSE-001" if A14 else "CDH-A13-PRIVATE-MANUAL-PRICE-UI-001" if A13 else "CDH-A12-LOCAL-PRICE-DAILY-DOM-AND-SAFE-IMPORT-PREVIEW-001" if A12 else "CDH-A11-WINDOWS-LOCAL-WEB-PREVIEW-001"
REPORT_LINE = "A14" if A14 else "A13_REV3" if A13_REV3 else "A13_REV2" if A13_REV2 else "A13" if A13 else "A12" if A12 else "A11"
ROUND = "R11" if A14 or A13 else "R10" if A12 else "R09"
NAME = "CDH_A_R11_004_REVIEW" if A14 else "CDH_A_R11_003_REVIEW" if A13_REV3 else "CDH_A_R11_002_REVIEW" if A13_REV2 else "CDH_A_R11_001_REVIEW" if A13 else "CDH_A_R10_001_REVIEW" if A12 else "CDH_A_R09_001_REVIEW"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
STAGE = ROOT / "review" / REPORT_LINE / ROUND / NAME
VERIFY = ROOT / "review" / REPORT_LINE / ROUND / f"{NAME}_verified_extract"
MANIFEST_NAME = "SHA256_MANIFEST.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_destination(base: Path, name: str) -> Path:
    pure = PurePosixPath(name.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeError(f"unsafe archive path: {name}")
    destination = base.joinpath(*pure.parts).resolve()
    destination.relative_to(base.resolve())
    return destination


def include_frontend(path: Path) -> bool:
    relative = path.relative_to(ROOT / "apps" / "price-web" / "frontend")
    blocked = {"node_modules", "reports", "__pycache__"}
    if any(part in blocked for part in relative.parts):
        return False
    if path.name == ".env" or path.suffix in {".pyc", ".pyo"} or path.name.endswith(".tsbuildinfo"):
        return False
    return path.is_file()


def include_preview(path: Path) -> bool:
    relative = path.relative_to(ROOT / "apps" / "price-web" / "local-preview-a11")
    if any(part in {"state", "runtime", "__pycache__"} for part in relative.parts):
        return False
    return path.is_file() and path.suffix not in {".pyc", ".pyo"}


def add_file(source: Path, relative: Path, copied: dict[str, Path]) -> None:
    key = relative.as_posix()
    if key in copied:
        raise RuntimeError(f"duplicate staged path: {key}")
    if not source.is_file() or source.is_symlink():
        raise RuntimeError(f"refusing non-regular source: {source}")
    copied[key] = source


def collect() -> dict[str, Path]:
    copied: dict[str, Path] = {}
    frontend = ROOT / "apps" / "price-web" / "frontend"
    for item in frontend.rglob("*"):
        if include_frontend(item):
            add_file(item, Path("apps/price-web/frontend") / item.relative_to(frontend), copied)
    preview = ROOT / "apps" / "price-web" / "local-preview-a11"
    for item in preview.rglob("*"):
        if include_preview(item):
            add_file(item, Path("apps/price-web/local-preview-a11") / item.relative_to(preview), copied)
    reports = ROOT / "reports" / REPORT_LINE
    for item in reports.rglob("*"):
        relative = item.relative_to(reports)
        if not item.is_file() or item.is_symlink() or any(part in {"browser_runtime", "runtime"} for part in relative.parts):
            continue
        if item.suffix.lower() not in {".md", ".json", ".jsonl", ".log", ".png"}:
            continue
        add_file(item, Path("reports") / REPORT_LINE / relative, copied)
    for relative in (Path("reports/A10/logs/FINAL_VALIDATION.json"), Path("reports/A10/evidence/HEADLESS_E2E.json"), Path("reports/A10/evidence/ACTUAL_B10_HTTP_PROBE.json")):
        add_file(ROOT / relative, relative, copied)
    if not A14:
        bundle_dir = "R11_FAST_TRACK_DELTA_20261105" if A13 else "UNIFIED_CONTINUOUS_20261105_R10" if A12 else "UNIFIED_CONTINUOUS_20261105_R09"
        bundle_name = "CDH_R11_FAST_TRACK_DELTA_20261105.zip" if A13 else "CDH_UNIFIED_CONTINUOUS_20261105_R10.zip" if A12 else "CDH_UNIFIED_CONTINUOUS_20261105_R09.zip"
        authority = ROOT / "input" / "orchestrator_bundles" / bundle_dir / "extracted"
        for item in authority.rglob("*"):
            if item.is_file() and not item.is_symlink():
                add_file(item, Path("authority") / ROUND / item.relative_to(authority), copied)
        input_zip = ROOT / "input" / "orchestrator_bundles" / bundle_dir / bundle_name
        add_file(input_zip, Path("input") / bundle_name, copied)
    a_dependency = "CDH_A_R11_003_REVIEW.zip" if A14 else "CDH_A_R11_002_REVIEW.zip" if A13_REV3 else "CDH_A_R11_001_REVIEW.zip" if A13_REV2 else "CDH_A_R10_001_REVIEW.zip" if A13 else "CDH_A_R09_001_REVIEW.zip" if A12 else "CDH_A_R08_001_REVIEW.zip"
    add_file(ROOT / "review" / "releases" / a_dependency, Path("dependencies") / a_dependency, copied)
    add_file(ROOT / "review/releases/CDH_B_R07_001_REVIEW.zip", Path("dependencies/CDH_B_R07_001_REVIEW.zip"), copied)
    if A12:
        add_file(ROOT / "review/releases/CDH_B_R10_001_REVIEW.zip", Path("dependencies/CDH_B_R10_001_REVIEW.zip"), copied)
        add_file(ROOT / "review/releases/CDH_C_R10_001_REVIEW.zip", Path("dependencies/CDH_C_R10_001_REVIEW.zip"), copied)
    if A13 or A14:
        add_file(ROOT / "review/releases/CDH_C_R10_002_REVIEW.zip", Path("dependencies/CDH_C_R10_002_REVIEW.zip"), copied)
        b15_name = "CDH_B_R11_002_REVIEW.zip" if A14 or A13_REV3 else "CDH_B_R11_001_REVIEW.zip"
        b15 = ROOT / "review" / "releases" / b15_name
        if b15.is_file():
            add_file(b15, Path("dependencies") / b15_name, copied)
    return copied


def validate_no_sensitive_names(paths: dict[str, Path]) -> None:
    blocked_names = {".env", "cookies.sqlite", "key4.db", "logins.json"}
    violations = [name for name in paths if any(part.casefold() in blocked_names for part in PurePosixPath(name).parts)]
    if violations:
        raise RuntimeError(f"sensitive names refused: {violations}")


def main() -> int:
    for target in (RELEASE, UPLOAD, STAGE, VERIFY):
        if target.exists():
            raise RuntimeError(f"refusing to overwrite existing delivery artifact: {target}")
    validation = json.loads((ROOT / "reports" / REPORT_LINE / "evidence" / "FINAL_VALIDATION.json").read_text(encoding="utf-8"))
    validation_pass = validation.get("all_available_scope_pass") if A14 or A12 or A13 else validation.get("all_pass")
    if validation_pass is not True:
        raise RuntimeError("FINAL_VALIDATION is not PASS")
    copied = collect(); validate_no_sensitive_names(copied)
    STAGE.mkdir(parents=True, exist_ok=False)
    for relative, source in sorted(copied.items()):
        destination = STAGE / Path(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    verification = {
        "schema_version": "CDH-A14-PACKAGE-VERIFICATION-1" if A14 else "CDH-A13-REV3-PACKAGE-VERIFICATION-1" if A13_REV3 else "CDH-A13-REV2-PACKAGE-VERIFICATION-1" if A13_REV2 else "CDH-A13-PACKAGE-VERIFICATION-1" if A13 else "CDH-A12-PACKAGE-VERIFICATION-1" if A12 else "CDH-A11-PACKAGE-VERIFICATION-1",
        "task_id": TASK_ID,
        "safe_extract": "PASS",
        "crc": "PASS",
        "manifest_match": "PASS",
        "missing": 0,
        "mismatch": 0,
        "undeclared": 0,
        "duplicates": 0,
        "note": "This archive is retained only if all post-build assertions below pass; failure aborts delivery and no READY status is emitted."
    }
    verification_path = STAGE / "PACKAGE_VERIFICATION.json"
    verification_path.write_text(json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    entries = []
    for item in sorted(STAGE.rglob("*")):
        if item.is_file() and item.name != MANIFEST_NAME:
            entries.append({"path": item.relative_to(STAGE).as_posix(), "size": item.stat().st_size, "sha256": sha256(item)})
    manifest = {"schema_version": "CDH-A14-REVIEW-MANIFEST-1" if A14 else "CDH-A13-REV3-REVIEW-MANIFEST-1" if A13_REV3 else "CDH-A13-REV2-REVIEW-MANIFEST-1" if A13_REV2 else "CDH-A13-REVIEW-MANIFEST-1" if A13 else "CDH-A12-REVIEW-MANIFEST-1" if A12 else "CDH-A11-REVIEW-MANIFEST-1", "task_id": TASK_ID, "payload_count": len(entries), "payloads": entries}
    manifest_path = STAGE / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(STAGE.rglob("*")):
            if item.is_file():
                archive.write(item, f"{NAME}/{item.relative_to(STAGE).as_posix()}")
    with zipfile.ZipFile(RELEASE) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("duplicate ZIP member")
        if archive.testzip() is not None:
            raise RuntimeError("ZIP CRC failure")
        for info in archive.infolist():
            if info.is_dir():
                continue
            destination = safe_destination(VERIFY, info.filename)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(info))
    extracted = VERIFY / NAME
    extracted_manifest_path = extracted / MANIFEST_NAME
    extracted_manifest = json.loads(extracted_manifest_path.read_text(encoding="utf-8"))
    expected = {item["path"]: (item["size"], item["sha256"]) for item in extracted_manifest["payloads"]}
    actual = {item.relative_to(extracted).as_posix(): (item.stat().st_size, sha256(item)) for item in extracted.rglob("*") if item.is_file() and item.name != MANIFEST_NAME}
    if actual != expected or len(actual) != extracted_manifest["payload_count"]:
        raise RuntimeError("extracted payload manifest mismatch")
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RELEASE, UPLOAD)
    release_sha = sha256(RELEASE)
    if sha256(UPLOAD) != release_sha or RELEASE.read_bytes() != UPLOAD.read_bytes():
        raise RuntimeError("upload copy byte identity failure")
    result = {
        "task_id": TASK_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "release": str(RELEASE),
        "upload_copy": str(UPLOAD),
        "size": RELEASE.stat().st_size,
        "sha256": release_sha,
        "manifest_sha256": sha256(manifest_path),
        "payload_count": len(actual),
        "crc": "PASS",
        "safe_extract": "PASS",
        "missing": 0,
        "mismatch": 0,
        "undeclared": 0,
        "duplicates": 0,
        "byte_identical_upload_copy": True,
        "status": "A14_R11_READY_FOR_REVIEW" if A14 else "A13_R11_REV3_READY_FOR_REVIEW" if A13_REV3 else "A13_R11_REV2_READY_FOR_REVIEW" if A13_REV2 else "A13_R11_READY_FOR_REVIEW_AVAILABLE_SCOPE" if A13 else "A12_R10_READY_FOR_REVIEW" if A12 else "A11_R09_READY_FOR_REVIEW",
    }
    result_path = ROOT / "reports" / REPORT_LINE / "evidence" / "PACKAGE_RESULT.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
