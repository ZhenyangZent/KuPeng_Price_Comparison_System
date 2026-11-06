from __future__ import annotations

import hashlib
import json
import shutil
import stat
import sys
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[3]
RELEASE_NAME = "CDH_A04_001_REVIEW"
STAGING = ROOT / f"review/A04/001/package/{RELEASE_NAME}"
TARGET = ROOT / f"review/releases/{RELEASE_NAME}.zip"
VERIFY_ROOT = ROOT / "review/A04/001/verification/extracted"
MANIFEST = "SHA256_MANIFEST.json"
IGNORE_PARTS = {".venv", ".downloads", "__pycache__", ".pytest_cache", "local_state", "test_tmp"}
SENSITIVE_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".reg", ".pem", ".key", ".pfx", ".p12"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def excluded(path: Path) -> bool:
    return any(part in IGNORE_PARTS for part in path.parts) or path.suffix.casefold() == ".pyc"


def copy_tree(relative: str) -> None:
    source = ROOT / relative
    target = STAGING / relative
    for path in source.rglob("*"):
        if not path.is_file() or excluded(path.relative_to(source)):
            continue
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or not name:
        raise RuntimeError(f"unsafe archive path: {name}")
    return unicodedata.normalize("NFC", name).casefold().rstrip(". ")


def payload_files() -> list[Path]:
    return sorted(path for path in STAGING.rglob("*") if path.is_file() and path.name != MANIFEST)


def write_manifest() -> dict[str, object]:
    files = [{"path": path.relative_to(STAGING).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in payload_files()]
    value = {"schema": "CDH-SHA256-MANIFEST-1", "task_id": "CDH-A04-WINDOWS-DAILY-APP-001", "source_status": "SOURCE_BLOCKED", "payload_count": len(files), "files": files}
    (STAGING / MANIFEST).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return value


def validate_sensitive() -> None:
    for path in STAGING.rglob("*"):
        if not path.is_file(): continue
        relative = path.relative_to(STAGING)
        lowered = relative.as_posix().casefold()
        if path.suffix.casefold() in SENSITIVE_SUFFIXES or any(token in lowered for token in ("cookie", "credential", "password", "token.txt", "secret")):
            raise RuntimeError(f"sensitive artifact rejected: {relative}")


def create_zip() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if TARGET.exists(): raise FileExistsError(f"release already exists: {TARGET}")
    with zipfile.ZipFile(TARGET, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(p for p in STAGING.rglob("*") if p.is_file()):
            archive.write(path, f"{RELEASE_NAME}/{path.relative_to(STAGING).as_posix()}")


def validate_zip(manifest: dict[str, object]) -> dict[str, object]:
    if VERIFY_ROOT.exists(): raise FileExistsError(f"verification directory exists: {VERIFY_ROOT}")
    VERIFY_ROOT.mkdir(parents=True)
    aliases: set[str] = set()
    with zipfile.ZipFile(TARGET) as archive:
        bad_crc = archive.testzip()
        for info in archive.infolist():
            alias = safe_name(info.filename)
            if alias in aliases: raise RuntimeError(f"archive alias collision: {info.filename}")
            aliases.add(alias)
            if info.flag_bits & 0x1: raise RuntimeError(f"encrypted entry: {info.filename}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode): raise RuntimeError(f"symlink entry: {info.filename}")
        if bad_crc is not None: raise RuntimeError(f"CRC failure: {bad_crc}")
        archive.extractall(VERIFY_ROOT)
    extracted = VERIFY_ROOT / RELEASE_NAME
    declared = {item["path"]: item for item in manifest["files"]}
    actual = {path.relative_to(extracted).as_posix(): path for path in extracted.rglob("*") if path.is_file() and path.name != MANIFEST}
    missing = sorted(set(declared) - set(actual)); undeclared = sorted(set(actual) - set(declared))
    mismatch = sorted(name for name in set(declared) & set(actual) if sha256(actual[name]) != declared[name]["sha256"] or actual[name].stat().st_size != declared[name]["bytes"])
    stored_manifest = json.loads((extracted / MANIFEST).read_text(encoding="utf-8"))
    if stored_manifest != manifest: raise RuntimeError("extracted manifest differs")
    if missing or undeclared or mismatch: raise RuntimeError(f"manifest failure: missing={missing}, undeclared={undeclared}, mismatch={mismatch}")
    return {"zip": str(TARGET), "size_bytes": TARGET.stat().st_size, "sha256": sha256(TARGET), "entries": len(actual) + 1, "payloads": len(actual), "missing": missing, "undeclared": undeclared, "mismatch": mismatch, "crc": "PASS", "path_safety": "PASS", "sensitive_content_gate": "PASS"}


def main() -> int:
    if STAGING.exists(): raise FileExistsError(f"staging exists: {STAGING}")
    STAGING.mkdir(parents=True)
    for relative in ("apps/a01", "apps/d01", "apps/d03", "scripts/d02", "scripts/d03", "tests/a01", "tests/a02", "tests/a03", "tests/a04", "tests/i02", "tests/d01", "tests/d02", "tests/d03", "docs/A04", "docs/D02", "reports/A04", "review/A04/001/evidence", "input/orchestrator_bundles/A04/extracted"):
        copy_tree(relative)
    crossline = ROOT / "input/orchestrator_bundles/I02/extracted/03_INDEPENDENT_CROSSLINE_12_CASES.py"
    destination = STAGING / "orchestrator_tests/03_INDEPENDENT_CROSSLINE_12_CASES.py"; destination.parent.mkdir(parents=True); shutil.copy2(crossline, destination)
    fixture = ROOT / "input/orchestrator_bundles/A01/extracted/11_SYNTHETIC_SNAPSHOT_FIXTURE.json"
    destination = STAGING / "input_contract/11_SYNTHETIC_SNAPSHOT_FIXTURE.json"; destination.parent.mkdir(parents=True); shutil.copy2(fixture, destination)
    for name in ("CDH_D02_001_REVIEW.zip", "CDH_D03_001_REVIEW.zip", "CDH_A03_001_REVIEW.zip"):
        destination = STAGING / "frozen_baselines" / name; destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT / "review/releases" / name, destination)
    d02_identity = STAGING / "review/releases/CDH_D02_001_REVIEW.zip"; d02_identity.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT / "review/releases/CDH_D02_001_REVIEW.zip", d02_identity)
    (STAGING / "RELEASE_README.md").write_text("# CDH A04 review\n\nOffline Windows manual-data milestone. Run `apps/a01/tools/a04_test_harness.py`; no live Coupang, Firefox, Registry, notifications, or transactions are authorized.\n", encoding="utf-8")
    (STAGING / "ARCHIVE_VALIDATION.json").write_text(json.dumps({"procedure": "a04_finalize.py validates safe paths, Unicode/case aliases, symlinks, encryption, CRC, clean extraction, per-file size and SHA-256", "required_result": "PASS", "extracted_test_command": "python -c bootstrap unittest discover tests/a04"}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    validate_sensitive()
    manifest = write_manifest()
    create_zip()
    result = validate_zip(manifest)
    validation = ROOT / "review/A04/001/RELEASE_VALIDATION.json"
    validation.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
