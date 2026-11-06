from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[4]
NAME = "CDH_A_R12_003_REVIEW"
STAGE = ROOT / "review" / "A16" / "R12" / NAME
VERIFY = ROOT / "review" / "A16" / "R12" / f"{NAME}_verified_extract"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
REPORT = ROOT / "reports" / "A16"


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
    target = base.joinpath(*pure.parts).resolve()
    target.relative_to(base.resolve())
    return target


def add(sources: list[tuple[Path, Path]], source: Path, relative: Path | None = None) -> None:
    if not source.is_file() or source.is_symlink():
        raise RuntimeError(f"invalid source: {source}")
    sources.append((source, relative or source.relative_to(ROOT)))


def add_tree(sources: list[tuple[Path, Path]], directory: Path) -> None:
    for item in sorted(directory.rglob("*")):
        if item.is_file() and not item.is_symlink():
            add(sources, item)


def main() -> int:
    for target in (STAGE, VERIFY, RELEASE, UPLOAD):
        if target.exists():
            raise RuntimeError(f"refusing overwrite: {target}")
    validation = json.loads((REPORT / "evidence" / "FINAL_VALIDATION.json").read_text(encoding="utf-8"))
    if validation.get("all_pass") is not True or validation.get("status") != "A16_READY_FOR_REVIEW" or validation.get("browser_gate") is not True:
        raise RuntimeError("A16 final validation gate failed")

    sources: list[tuple[Path, Path]] = []
    for name in ("README.md", "Start-CDH-MVP.cmd", "Stop-CDH-MVP.cmd", "Status-CDH-MVP.cmd"):
        add(sources, ROOT / name)
    add_tree(sources, ROOT / "scripts" / "windows-mvp")
    add(sources, ROOT / "docs" / "user-guides" / "WINDOWS_LOCAL_MVP_FIRST_USE.md")

    preview = ROOT / "apps" / "price-web" / "local-preview-a11"
    for name in ("control.py", "preview_server.py", "README.md", "Start-LocalPreview.cmd", "Start-LocalPreview.ps1", "Status-LocalPreview.ps1", "Stop-LocalPreview.cmd", "Stop-LocalPreview.ps1"):
        add(sources, preview / name)
    for name in ("browser-e2e-a16.mjs", "run_final_validation_a16.py", "write_dist_manifest.py", "package_a16.py"):
        add(sources, preview / "scripts" / name)
    for name in ("test_preview.py", "test_a16_first_use.py"):
        add(sources, preview / "tests" / name)

    frontend = ROOT / "apps" / "price-web" / "frontend"
    for directory in (frontend / "src", frontend / "tests", frontend / "scripts", frontend / "dist"):
        add_tree(sources, directory)
    for name in ("package.json", "package-lock.json", "index.html", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "vite.config.mjs"):
        path = frontend / name
        if path.is_file():
            add(sources, path)

    for name in ("STATUS.json", "IMPLEMENTATION.md", "TEST_RESULTS.md", "CHANGE_LIST.md", "RISK_REPORT.md", "DEVELOPMENT_LOG.md", "INPUT_DEPENDENCY.json"):
        add(sources, REPORT / name)
    add_tree(sources, REPORT / "logs")
    add_tree(sources, REPORT / "evidence")
    add_tree(sources, REPORT / "screenshots")

    for name in ("CDH_A_R12_002_REVIEW.zip", "CDH_B_R12_003_REVIEW.zip"):
        add(sources, ROOT / "review" / "releases" / name, Path("dependencies") / name)

    relative_names = [relative.as_posix() for _, relative in sources]
    if len(relative_names) != len(set(relative_names)) or len(relative_names) != len({name.casefold() for name in relative_names}):
        raise RuntimeError("duplicate staged path")
    STAGE.mkdir(parents=True)
    for source, relative in sources:
        destination = STAGE / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    entries = [{"path": item.relative_to(STAGE).as_posix(), "bytes": item.stat().st_size, "sha256": digest(item)} for item in sorted(STAGE.rglob("*")) if item.is_file()]
    manifest = {"schema_version": "CDH-A16-REVIEW-MANIFEST-1", "task_id": "CDH-A16-LOCAL-MVP-FIRST-USE-001", "status": "A16_READY_FOR_REVIEW", "payload_count": len(entries), "payloads": entries}
    manifest_path = STAGE / "SHA256_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(STAGE.rglob("*")):
            if item.is_file():
                archive.write(item, f"{NAME}/{item.relative_to(STAGE).as_posix()}")

    with zipfile.ZipFile(RELEASE) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise RuntimeError("duplicate ZIP member")
        if archive.testzip() is not None:
            raise RuntimeError("ZIP CRC failure")
        for info in archive.infolist():
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RuntimeError(f"symlink member: {info.filename}")
            lowered = info.filename.casefold()
            if any(part.casefold() in {".env", "__pycache__", "node_modules", "chrome-profile", "browser_runtime"} for part in PurePosixPath(info.filename).parts):
                raise RuntimeError(f"forbidden member: {info.filename}")
            if lowered.endswith((".pyc", ".pyo", ".sqlite", ".sqlite3", "control.token")):
                raise RuntimeError(f"forbidden artifact: {info.filename}")
            if info.is_dir():
                continue
            destination = safe(VERIFY, info.filename)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(info))

    extracted = VERIFY / NAME
    declared = json.loads((extracted / "SHA256_MANIFEST.json").read_text(encoding="utf-8"))["payloads"]
    expected = {item["path"]: (item["bytes"], item["sha256"]) for item in declared}
    actual = {item.relative_to(extracted).as_posix(): (item.stat().st_size, digest(item)) for item in extracted.rglob("*") if item.is_file() and item.name != "SHA256_MANIFEST.json"}
    if expected != actual:
        raise RuntimeError("safe extract manifest mismatch")

    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RELEASE, UPLOAD)
    if digest(RELEASE) != digest(UPLOAD) or RELEASE.read_bytes() != UPLOAD.read_bytes():
        raise RuntimeError("upload copy mismatch")
    result = {
        "schema_version": "CDH-A16-PACKAGE-RESULT-1",
        "task_id": "CDH-A16-LOCAL-MVP-FIRST-USE-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "A16_READY_FOR_REVIEW",
        "release": str(RELEASE),
        "upload_copy": str(UPLOAD),
        "size": RELEASE.stat().st_size,
        "sha256": digest(RELEASE),
        "manifest_sha256": digest(manifest_path),
        "payload_count": len(actual),
        "crc": "PASS",
        "safe_extract": "PASS",
        "missing": 0,
        "mismatch": 0,
        "undeclared": 0,
        "duplicates": 0,
        "byte_identical_upload_copy": True,
    }
    (REPORT / "evidence" / "PACKAGE_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
