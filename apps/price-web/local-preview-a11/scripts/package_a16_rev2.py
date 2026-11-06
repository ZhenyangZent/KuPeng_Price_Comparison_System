from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[4]
NAME = "CDH_A_R12_004_REVIEW"
STAGE = ROOT / "review" / "A16_REV2" / "R12" / NAME
VERIFY = ROOT / "review" / "A16_REV2" / "R12" / f"{NAME}_verified_extract"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
REPORT = ROOT / "reports" / "A16_REV2"


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
    if validation.get("all_pass") is not True or validation.get("status") != "A16_REV2_READY_FOR_REVIEW" or validation.get("cmd_e2e_gate") is not True or validation.get("crlf_gate") is not True:
        raise RuntimeError("A16 REV2 validation gate failed")

    sources: list[tuple[Path, Path]] = []
    for name in ("README.md", "Start-CDH-MVP.cmd", "Status-CDH-MVP.cmd", "Stop-CDH-MVP.cmd"):
        add(sources, ROOT / name)
    add_tree(sources, ROOT / "scripts" / "windows-mvp")
    add(sources, ROOT / "docs" / "user-guides" / "WINDOWS_LOCAL_MVP_FIRST_USE.md")

    preview = ROOT / "apps" / "price-web" / "local-preview-a11"
    for name in ("control.py", "preview_server.py", "README.md", "Start-LocalPreview.cmd", "Start-LocalPreview.ps1", "Status-LocalPreview.ps1", "Stop-LocalPreview.cmd", "Stop-LocalPreview.ps1"):
        add(sources, preview / name)
    for name in ("test_a16_rev2_cmd.py", "run_final_validation_a16_rev2.py", "write_dist_manifest.py", "package_a16_rev2.py"):
        add(sources, preview / "scripts" / name)
    for name in ("test_preview.py", "test_a16_first_use.py", "test_a16_rev2.py"):
        add(sources, preview / "tests" / name)

    frontend = ROOT / "apps" / "price-web" / "frontend"
    add_tree(sources, frontend / "dist")
    for name in ("package.json", "package-lock.json", "index.html"):
        add(sources, frontend / name)

    for name in ("STATUS.json", "IMPLEMENTATION.md", "DEFECT_MATRIX.md", "TEST_RESULTS.md", "CHANGE_LIST.md", "RISK_REPORT.md", "INPUT_DEPENDENCY.json"):
        add(sources, REPORT / name)
    add_tree(sources, REPORT / "logs")
    add_tree(sources, REPORT / "evidence")

    for name in ("CDH_A_R12_003_REVIEW.zip", "CDH_H_R12_003_REVIEW.zip"):
        add(sources, ROOT / "review" / "releases" / name, Path("dependencies") / name)

    relative_names = [relative.as_posix() for _, relative in sources]
    if len(relative_names) != len(set(relative_names)) or len(relative_names) != len({name.casefold() for name in relative_names}):
        raise RuntimeError("duplicate staged path")
    STAGE.mkdir(parents=True)
    for source, relative in sources:
        destination = STAGE / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    for name in ("Start-CDH-MVP.cmd", "Status-CDH-MVP.cmd", "Stop-CDH-MVP.cmd"):
        payload = (STAGE / name).read_bytes()
        if b"\r\n" not in payload or b"\n" in payload.replace(b"\r\n", b""):
            raise RuntimeError(f"CMD line-ending gate failed: {name}")

    entries = [{"path": item.relative_to(STAGE).as_posix(), "bytes": item.stat().st_size, "sha256": digest(item)} for item in sorted(STAGE.rglob("*")) if item.is_file()]
    manifest = {"schema_version": "CDH-A16-REV2-REVIEW-MANIFEST-1", "task_id": "CDH-A16-LOCAL-MVP-FIRST-USE-001", "revision": "REV2", "status": "A16_REV2_READY_FOR_REVIEW", "payload_count": len(entries), "payloads": entries}
    manifest_path = STAGE / "SHA256_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(STAGE.rglob("*")):
            if item.is_file():
                archive.write(item, f"{NAME}/{item.relative_to(STAGE).as_posix()}")

    with zipfile.ZipFile(RELEASE) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}) or archive.testzip() is not None:
            raise RuntimeError("ZIP CRC or duplicate failure")
        for info in archive.infolist():
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError(f"symlink member: {info.filename}")
            parts = {part.casefold() for part in PurePosixPath(info.filename).parts}
            if parts & {".env", "__pycache__", "node_modules", "runtime", "test_state", "chrome-profile"}:
                raise RuntimeError(f"forbidden member: {info.filename}")
            if info.filename.casefold().endswith((".pyc", ".pyo", ".sqlite", ".sqlite3", "control.token")):
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
    for name in ("Start-CDH-MVP.cmd", "Status-CDH-MVP.cmd", "Stop-CDH-MVP.cmd"):
        payload = (extracted / name).read_bytes()
        if b"\r\n" not in payload or b"\n" in payload.replace(b"\r\n", b""):
            raise RuntimeError(f"extracted CMD line-ending failure: {name}")

    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RELEASE, UPLOAD)
    if digest(RELEASE) != digest(UPLOAD) or RELEASE.read_bytes() != UPLOAD.read_bytes():
        raise RuntimeError("upload copy mismatch")
    result = {
        "schema_version": "CDH-A16-REV2-PACKAGE-RESULT-1",
        "task_id": "CDH-A16-LOCAL-MVP-FIRST-USE-001",
        "revision": "REV2",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "A16_REV2_READY_FOR_REVIEW",
        "release": str(RELEASE),
        "upload_copy": str(UPLOAD),
        "size": RELEASE.stat().st_size,
        "sha256": digest(RELEASE),
        "manifest_sha256": digest(manifest_path),
        "payload_count": len(actual),
        "cmd_crlf_gate": "PASS",
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
