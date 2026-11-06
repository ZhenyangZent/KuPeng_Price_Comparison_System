from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[4]
NAME = "CDH_A_R12_002_REVIEW"
STAGE = ROOT / "review" / "A15" / "R12" / NAME
VERIFY = ROOT / "review" / "A15" / "R12" / f"{NAME}_verified_extract"
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
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts) or "\\" in name or "\x00" in name:
        raise RuntimeError(f"unsafe member: {name}")
    target = base.joinpath(*pure.parts).resolve(); target.relative_to(base.resolve()); return target


def add(sources: list[tuple[Path, Path]], source: Path, relative: Path | None = None) -> None:
    if not source.is_file() or source.is_symlink():
        raise RuntimeError(f"invalid source: {source}")
    sources.append((source, relative or source.relative_to(ROOT)))


def main() -> int:
    for target in (STAGE, VERIFY, RELEASE, UPLOAD):
        if target.exists():
            raise RuntimeError(f"refusing overwrite: {target}")
    validation = json.loads((ROOT / "reports/A15_REV2/evidence/FINAL_VALIDATION.json").read_text(encoding="utf-8"))
    if validation.get("all_available_scope_pass") is not True or validation.get("browser_all_pass") is not True or validation.get("chrome_exit_code") != 0 or validation.get("actual_integration") != "ACTUAL_A15_REV2_UI_TO_B16_REV3_LOCAL_API":
        raise RuntimeError("A15 REV2 validation gate failed")
    sources: list[tuple[Path, Path]] = []
    preview = ROOT / "apps" / "price-web" / "local-preview-a11"
    for name in ("control.py", "preview_server.py", "README.md", "Start-LocalPreview.cmd", "Start-LocalPreview.ps1", "Status-LocalPreview.ps1", "Stop-LocalPreview.cmd", "Stop-LocalPreview.ps1"):
        add(sources, preview / name)
    for name in ("browser-e2e-a15.mjs", "run_final_validation_a15.py", "write_dist_manifest.py", "package_a15_rev2.py"):
        add(sources, preview / "scripts" / name)
    add(sources, preview / "tests" / "test_preview.py")
    frontend = ROOT / "apps" / "price-web" / "frontend"
    for item in sorted((frontend / "dist").rglob("*")):
        if item.is_file() and not item.is_symlink(): add(sources, item)
    for name in ("package.json", "package-lock.json", "index.html"):
        add(sources, frontend / name)
    report = ROOT / "reports" / "A15_REV2"
    for name in ("STATUS.json", "WAITING_FOR_UPSTREAM_BEFORE.json", "IMPLEMENTATION.md", "TEST_RESULTS.md", "CHANGE_LIST.md", "RISK_REPORT.md"):
        add(sources, report / name)
    for directory in (report / "logs", report / "screenshots"):
        for item in sorted(directory.rglob("*")):
            if item.is_file() and not item.is_symlink(): add(sources, item)
    for item in sorted((report / "evidence").glob("*.json")): add(sources, item)
    for item in sorted((report / "evidence" / "server_logs").glob("*.log")): add(sources, item)
    b16_root = ROOT / "input" / "crossline" / "A15" / "R12" / "B16_REV3" / "CDH_B_R12_003_REVIEW" / "services" / "private_batch_import_b16"
    for source in (b16_root / "API_CONTRACT.md", b16_root / "A15_HANDOFF.md", b16_root / "openapi" / "b16.openapi.json", *sorted((b16_root / "examples").glob("*"))):
        add(sources, source, Path("dependencies/B16_REV3_CONTRACT") / source.relative_to(b16_root))
    for name in ("CDH_A_R12_001_REVIEW.zip", "CDH_B_R12_003_REVIEW.zip"):
        add(sources, ROOT / "review" / "releases" / name, Path("dependencies") / name)
    if len({relative.as_posix().casefold() for _, relative in sources}) != len(sources):
        raise RuntimeError("duplicate staged path")
    STAGE.mkdir(parents=True)
    for source, relative in sources:
        destination = STAGE / relative; destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    dependency = {
        "schema_version": "CDH-A15-REV2-INPUT-DEPENDENCY-1", "task_id": "CDH-A15-BATCH-IMPORT-UI-001", "revision": "REV2",
        "inputs": {
            "A15_ORIGINAL": {"filename": "CDH_A_R12_001_REVIEW.zip", "sha256": "5cc44dedd910ff9b2055cfc2772ad0c3d6db627ffc818794f81fd3d9b5552d4b"},
            "B16_REV3": {"filename": "CDH_B_R12_003_REVIEW.zip", "sha256": "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7", "manifest_sha256": "1b2f09586aa9528987d3b92b1292d97aa2fa6bfb89d413520a965d284e440188"},
        },
        "actual_integration": "ACTUAL_A15_REV2_UI_TO_B16_REV3_LOCAL_API", "api_route_or_request_schema_change_count": 0, "frontend_source_change_count": 0,
    }
    (STAGE / "INPUT_DEPENDENCY.json").write_text(json.dumps(dependency, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    entries = [{"path": item.relative_to(STAGE).as_posix(), "bytes": item.stat().st_size, "sha256": digest(item)} for item in sorted(STAGE.rglob("*")) if item.is_file()]
    manifest = {"schema_version": "CDH-A15-REV2-REVIEW-MANIFEST-1", "task_id": "CDH-A15-BATCH-IMPORT-UI-001", "revision": "REV2", "status": "A15_REV2_READY_FOR_REVIEW", "payload_count": len(entries), "payloads": entries}
    manifest_path = STAGE / "SHA256_MANIFEST.json"; manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(STAGE.rglob("*")):
            if item.is_file(): archive.write(item, f"{NAME}/{item.relative_to(STAGE).as_posix()}")
    with zipfile.ZipFile(RELEASE) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}) or archive.testzip() is not None:
            raise RuntimeError("ZIP CRC or duplicate failure")
        if any("/.env" in name.casefold() or "__pycache__" in name.casefold() or name.casefold().endswith((".pyc", ".pyo", ".sqlite", ".sqlite3")) for name in names):
            raise RuntimeError("forbidden artifact")
        for info in archive.infolist():
            if info.is_dir(): continue
            destination = safe(VERIFY, info.filename); destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(archive.read(info))
    extracted = VERIFY / NAME
    declared = json.loads((extracted / "SHA256_MANIFEST.json").read_text(encoding="utf-8"))["payloads"]
    expected = {item["path"]: (item["bytes"], item["sha256"]) for item in declared}
    actual = {item.relative_to(extracted).as_posix(): (item.stat().st_size, digest(item)) for item in extracted.rglob("*") if item.is_file() and item.name != "SHA256_MANIFEST.json"}
    if expected != actual: raise RuntimeError("safe extract manifest mismatch")
    UPLOAD.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(RELEASE, UPLOAD)
    if digest(RELEASE) != digest(UPLOAD) or RELEASE.read_bytes() != UPLOAD.read_bytes(): raise RuntimeError("upload copy mismatch")
    result = {"task_id": "CDH-A15-BATCH-IMPORT-UI-001", "revision": "REV2", "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "status": "A15_REV2_READY_FOR_REVIEW", "release": str(RELEASE), "upload_copy": str(UPLOAD), "size": RELEASE.stat().st_size, "sha256": digest(RELEASE), "manifest_sha256": digest(manifest_path), "payload_count": len(actual), "crc": "PASS", "safe_extract": "PASS", "missing": 0, "mismatch": 0, "undeclared": 0, "duplicates": 0, "byte_identical_upload_copy": True}
    (report / "evidence" / "PACKAGE_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
