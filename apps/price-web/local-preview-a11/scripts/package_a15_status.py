from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[4]
NAME = "CDH_A_R11_005_STATUS_ONLY"
STAGE = ROOT / "review" / "A15" / "R11" / NAME
VERIFY = ROOT / "review" / "A15" / "R11" / f"{NAME}_verified_extract"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe(base: Path, name: str) -> Path:
    pure = PurePosixPath(name.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeError(f"unsafe member: {name}")
    target = base.joinpath(*pure.parts).resolve(); target.relative_to(base.resolve()); return target


def main() -> int:
    for target in (STAGE, VERIFY, RELEASE, UPLOAD):
        if target.exists():
            raise RuntimeError(f"refusing overwrite: {target}")
    validation = json.loads((ROOT / "reports/A15/evidence/VALIDATION.json").read_text(encoding="utf-8"))
    if validation.get("all_available_scope_pass") is not True or validation.get("b16_contract_available") is not False:
        raise RuntimeError("A15 status validation gate failed")
    relative_files = [
        "apps/price-web/frontend/src/BatchImportPanel.tsx",
        "apps/price-web/frontend/src/batchImportPreview.ts",
        "apps/price-web/frontend/src/CouponApiExperience.tsx",
        "apps/price-web/frontend/src/styles.css",
        "apps/price-web/frontend/tests/a15_batch_import_preflight.test.tsx",
        "apps/price-web/frontend/package.json",
        "apps/price-web/frontend/package-lock.json",
        "apps/price-web/local-preview-a11/scripts/package_a15_status.py",
        "reports/A15/STATUS.json",
        "reports/A15/TEST_RESULTS.md",
        "reports/A15/RISK_REPORT.md",
        "reports/A15/evidence/VALIDATION.json",
    ]
    relative_files.extend(item.relative_to(ROOT).as_posix() for item in sorted((ROOT / "apps/price-web/frontend/dist").rglob("*")) if item.is_file())
    if len(relative_files) != len(set(relative_files)):
        raise RuntimeError("duplicate staged path")
    STAGE.mkdir(parents=True)
    for relative in relative_files:
        source = ROOT / relative
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"invalid source: {source}")
        destination = STAGE / relative; destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    dependency = {
        "schema_version": "CDH-A15-INPUT-DEPENDENCY-1",
        "status": "WAITING_FOR_UPSTREAM",
        "available": {
            "A14": {"filename": "CDH_A_R11_004_REVIEW.zip", "sha256": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160"},
            "B15_REV2": {"filename": "CDH_B_R11_002_REVIEW.zip", "sha256": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe"},
            "H10_REV3": {"filename": "CDH_H_R11_005_REVIEW.zip", "sha256": "7cba1e0e6031a9f8abb0a13326cfe7d493602adb41b4b5514df07a13153c9ac4"}
        },
        "missing": "B16_FORMAL_REVIEW_ZIP_CONTRACT_AND_SHA256",
        "b16_api_tests": "NOT_RUN_INPUT_UNAVAILABLE"
    }
    (STAGE / "INPUT_DEPENDENCY.json").write_text(json.dumps(dependency, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    entries = [{"path": item.relative_to(STAGE).as_posix(), "size": item.stat().st_size, "sha256": digest(item)} for item in sorted(STAGE.rglob("*")) if item.is_file()]
    manifest = {"schema_version": "CDH-A15-STATUS-MANIFEST-1", "task_id": "CDH-A15-BATCH-IMPORT-UI-001", "status": "WAITING_FOR_UPSTREAM_WITH_UI_PREWORK_READY", "payload_count": len(entries), "payloads": entries}
    manifest_path = STAGE / "SHA256_MANIFEST.json"; manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(STAGE.rglob("*")):
            if item.is_file(): archive.write(item, f"{NAME}/{item.relative_to(STAGE).as_posix()}")
    with zipfile.ZipFile(RELEASE) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.testzip() is not None: raise RuntimeError("ZIP integrity failure")
        for info in archive.infolist():
            if info.is_dir(): continue
            destination = safe(VERIFY, info.filename); destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(archive.read(info))
    extracted = VERIFY / NAME
    extracted_manifest = json.loads((extracted / "SHA256_MANIFEST.json").read_text(encoding="utf-8"))
    expected = {item["path"]: (item["size"], item["sha256"]) for item in extracted_manifest["payloads"]}
    actual = {item.relative_to(extracted).as_posix(): (item.stat().st_size, digest(item)) for item in extracted.rglob("*") if item.is_file() and item.name != "SHA256_MANIFEST.json"}
    if expected != actual: raise RuntimeError("safe extract manifest mismatch")
    UPLOAD.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(RELEASE, UPLOAD)
    if digest(RELEASE) != digest(UPLOAD) or RELEASE.read_bytes() != UPLOAD.read_bytes(): raise RuntimeError("upload copy mismatch")
    result = {"task_id": "CDH-A15-BATCH-IMPORT-UI-001", "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "status": "WAITING_FOR_UPSTREAM_WITH_UI_PREWORK_READY", "release": str(RELEASE), "upload_copy": str(UPLOAD), "size": RELEASE.stat().st_size, "sha256": digest(RELEASE), "manifest_sha256": digest(manifest_path), "payload_count": len(actual), "crc": "PASS", "safe_extract": "PASS", "missing": 0, "mismatch": 0, "undeclared": 0, "duplicates": 0, "byte_identical_upload_copy": True}
    (ROOT / "reports/A15/evidence/PACKAGE_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
