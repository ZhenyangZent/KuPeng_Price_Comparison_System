from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[4]
NAME = "CDH_A_R12_001_REVIEW"
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


def include_tree(base: Path, *, excludes: set[str]) -> list[Path]:
    return [item for item in sorted(base.rglob("*")) if item.is_file() and not item.is_symlink() and not any(part in excludes for part in item.relative_to(base).parts)]


def main() -> int:
    for target in (STAGE, VERIFY, RELEASE, UPLOAD):
        if target.exists():
            raise RuntimeError(f"refusing overwrite: {target}")
    validation = json.loads((ROOT / "reports/A15_FINAL/evidence/FINAL_VALIDATION.json").read_text(encoding="utf-8"))
    if validation.get("all_available_scope_pass") is not True or validation.get("browser_all_pass") is not True or validation.get("chrome_exit_code") != 0:
        raise RuntimeError("A15 final validation gate failed")
    sources: list[tuple[Path, Path]] = []
    frontend = ROOT / "apps" / "price-web" / "frontend"
    frontend_excludes = {"node_modules", ".vitest-temp", "reports", "upstream", "__pycache__"}
    for source in include_tree(frontend, excludes=frontend_excludes):
        if source.name.endswith(".tsbuildinfo") or source.name == ".env.example":
            continue
        sources.append((source, source.relative_to(ROOT)))
    preview = ROOT / "apps" / "price-web" / "local-preview-a11"
    for source in include_tree(preview, excludes={"__pycache__", "runtime", "state", "server_logs", "debug_logs"}):
        sources.append((source, source.relative_to(ROOT)))
    report = ROOT / "reports" / "A15_FINAL"
    for directory in (report / "logs", report / "screenshots"):
        for source in include_tree(directory, excludes=set()):
            sources.append((source, source.relative_to(ROOT)))
    for source in sorted((report / "evidence").glob("*.json")):
        sources.append((source, source.relative_to(ROOT)))
    for source in sorted((report / "evidence" / "server_logs").glob("*.log")):
        sources.append((source, source.relative_to(ROOT)))
    for name in ("IMPLEMENTATION.md", "TEST_RESULTS.md", "CHANGE_LIST.md", "RISK_REPORT.md", "DELIVERY_STATUS.md"):
        source = report / name; sources.append((source, source.relative_to(ROOT)))
    b16_contract = ROOT / "input" / "crossline" / "A15" / "R12" / "B16" / "CDH_B_R12_001_REVIEW" / "services" / "private_batch_import_b16"
    contract_sources = [b16_contract / "API_CONTRACT.md", b16_contract / "A15_HANDOFF.md", b16_contract / "openapi" / "b16.openapi.json", *sorted((b16_contract / "examples").glob("*"))]
    for source in contract_sources:
        sources.append((source, Path("dependencies/B16_CONTRACT") / source.relative_to(b16_contract)))
    for name in ("CDH_A_R11_005_STATUS_ONLY.zip", "CDH_B_R12_001_REVIEW.zip"):
        source = ROOT / "review" / "releases" / name; sources.append((source, Path("dependencies") / name))
    if len({destination.as_posix().casefold() for _, destination in sources}) != len(sources):
        raise RuntimeError("duplicate staged path")
    STAGE.mkdir(parents=True)
    for source, relative in sources:
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"invalid source: {source}")
        destination = STAGE / relative; destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    dependency = {
        "schema_version": "CDH-A15-INPUT-DEPENDENCY-2", "task_id": "CDH-A15-BATCH-IMPORT-UI-001",
        "inputs": {
            "A15_PREWORK": {"filename": "CDH_A_R11_005_STATUS_ONLY.zip", "sha256": "48861846f750a95db75d8ef0e4f80613c2f13794b3cfb2e7ba2a957e79b91e4b"},
            "B16_R12": {"filename": "CDH_B_R12_001_REVIEW.zip", "sha256": "d2149952fe1693381f74ac639a770b393b8703a368df68eea990cd5e231cf23b", "manifest_sha256": "5b8682f166320f7eb34119e8d1f4ccf90873af768c2bf45bcf06a0b51d72808c"},
        },
        "actual_integration": "ACTUAL_A15_UI_TO_B16_R12_LOCAL_API", "formal_database_write_count": 0,
    }
    (STAGE / "INPUT_DEPENDENCY.json").write_text(json.dumps(dependency, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    reproduction = """# A15 reproduction\n\n1. Restore the project dependencies with `npm ci` in `apps/price-web/frontend`.\n2. Keep the exact A14/B13/B14/B15/C11 releases required by B16 in `review/releases`.\n3. Run `python apps/price-web/local-preview-a11/scripts/run_final_validation_a15.py` in an isolated Windows loopback environment.\n4. Do not use a formal database, real `.env`, Firefox, Registry, or external commerce service.\n"""
    (STAGE / "REPRODUCE.md").write_text(reproduction, encoding="utf-8")
    entries = [{"path": item.relative_to(STAGE).as_posix(), "bytes": item.stat().st_size, "sha256": digest(item)} for item in sorted(STAGE.rglob("*")) if item.is_file()]
    manifest = {"schema_version": "CDH-A15-REVIEW-MANIFEST-1", "task_id": "CDH-A15-BATCH-IMPORT-UI-001", "status": "A15_READY_FOR_REVIEW", "payload_count": len(entries), "payloads": entries}
    manifest_path = STAGE / "SHA256_MANIFEST.json"; manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(STAGE.rglob("*")):
            if item.is_file(): archive.write(item, f"{NAME}/{item.relative_to(STAGE).as_posix()}")
    with zipfile.ZipFile(RELEASE) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}) or archive.testzip() is not None:
            raise RuntimeError("ZIP CRC or duplicate failure")
        if any("/.env" in name.casefold() or "__pycache__" in name.casefold() or name.casefold().endswith((".pyc", ".pyo")) for name in names):
            raise RuntimeError("forbidden artifact")
        for info in archive.infolist():
            if info.is_dir(): continue
            destination = safe(VERIFY, info.filename); destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(archive.read(info))
    extracted = VERIFY / NAME
    extracted_manifest = json.loads((extracted / "SHA256_MANIFEST.json").read_text(encoding="utf-8"))
    expected = {item["path"]: (item["bytes"], item["sha256"]) for item in extracted_manifest["payloads"]}
    actual = {item.relative_to(extracted).as_posix(): (item.stat().st_size, digest(item)) for item in extracted.rglob("*") if item.is_file() and item.name != "SHA256_MANIFEST.json"}
    if expected != actual:
        raise RuntimeError("safe extract manifest mismatch")
    UPLOAD.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(RELEASE, UPLOAD)
    if digest(RELEASE) != digest(UPLOAD) or RELEASE.read_bytes() != UPLOAD.read_bytes():
        raise RuntimeError("upload copy mismatch")
    result = {"task_id": "CDH-A15-BATCH-IMPORT-UI-001", "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "status": "A15_READY_FOR_REVIEW", "release": str(RELEASE), "upload_copy": str(UPLOAD), "size": RELEASE.stat().st_size, "sha256": digest(RELEASE), "manifest_sha256": digest(manifest_path), "payload_count": len(actual), "crc": "PASS", "safe_extract": "PASS", "missing": 0, "mismatch": 0, "undeclared": 0, "duplicates": 0, "byte_identical_upload_copy": True}
    (ROOT / "reports" / "A15_FINAL" / "evidence" / "PACKAGE_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
