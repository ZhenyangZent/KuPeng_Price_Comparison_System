from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PACKAGE_NAME = "CDH_D02_001_REVIEW"
COPY_TREES = (
    "apps/d01",
    "scripts/d02",
    "tests/d01",
    "tests/d02",
    "docs/D02",
    "reports/D02",
    "input/orchestrator_bundles/D02",
    "review/D02/evidence",
    "review/D02/logs",
)
COPY_FILES = ("review/D02/REVIEW_REPORT.md",)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ignored(path: Path) -> bool:
    return (
        any(part in {"__pycache__", "test_tmp", "package", "verify_extracted"} for part in path.parts)
        or path.suffix in {".pyc", ".pyo"}
        or path.name.startswith(".tmp")
        or path.name.endswith((".sqlite3-wal", ".sqlite3-shm"))
    )


def copy_tree(root: Path, relative: str, staging: Path) -> None:
    source = root / relative
    if not source.exists():
        return
    for path in sorted(source.rglob("*")):
        if ignored(path):
            continue
        if path.is_symlink():
            raise RuntimeError(f"symlink forbidden in package: {path}")
        if path.is_file():
            destination = staging / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def build(root: Path, output: Path) -> dict[str, object]:
    package_root = root / "review/D02/package" / PACKAGE_NAME
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True)
    for relative in COPY_TREES:
        copy_tree(root, relative, package_root)
    for relative in COPY_FILES:
        source = root / relative
        if source.is_file():
            destination = package_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    payloads = []
    for path in sorted(package_root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(package_root).as_posix()
            if relative not in {"MANIFEST.json", "SHA256SUMS.txt"}:
                payloads.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    sums_path = package_root / "SHA256SUMS.txt"
    sums_path.write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in payloads),
        encoding="utf-8",
        newline="\n",
    )
    manifest = {
        "contract": "CDH_D02_001_REVIEW_V1",
        "task_id": "CDH-D02-LOCAL-SYNC-RECEIPTS-001",
        "authority": "AUTHORIZED_LOCAL_SYNTHETIC_SYNC_CODE_ONLY",
        "status": "D02_READY_FOR_REVIEW",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "payload_count": len(payloads),
        "payload_bytes": sum(entry["bytes"] for entry in payloads),
        "sha256sums_sha256": sha256(sums_path),
        "entries": payloads,
    }
    manifest_path = package_root / "MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=False) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                name = (PurePosixPath(PACKAGE_NAME) / path.relative_to(package_root).as_posix()).as_posix()
                archive.write(path, name)
    return {"package_root": str(package_root), "zip": str(output), "zip_sha256": sha256(output), **manifest}


def validate_and_extract(output: Path, extraction_parent: Path) -> dict[str, object]:
    destination = extraction_parent / PACKAGE_NAME
    if destination.exists():
        shutil.rmtree(destination)
    extraction_parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise RuntimeError("duplicate or case-colliding ZIP member")
        for info in archive.infolist():
            pure = PurePosixPath(info.filename)
            if pure.is_absolute() or ".." in pure.parts or not pure.parts or pure.parts[0] != PACKAGE_NAME:
                raise RuntimeError(f"unsafe ZIP path: {info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError(f"ZIP symlink forbidden: {info.filename}")
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"CRC failure: {bad}")
        archive.extractall(extraction_parent)
    manifest_path = destination / "MANIFEST.json"
    sums_path = destination / "SHA256SUMS.txt"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = {entry["path"]: entry for entry in manifest["entries"]}
    actual = {
        path.relative_to(destination).as_posix(): path
        for path in destination.rglob("*")
        if path.is_file() and path.relative_to(destination).as_posix() not in {"MANIFEST.json", "SHA256SUMS.txt"}
    }
    errors: list[str] = []
    for name in sorted(set(declared) | set(actual)):
        if name not in declared:
            errors.append(f"undeclared:{name}")
        elif name not in actual:
            errors.append(f"missing:{name}")
        else:
            entry = declared[name]
            if actual[name].stat().st_size != entry["bytes"] or sha256(actual[name]) != entry["sha256"]:
                errors.append(f"mismatch:{name}")
    if sha256(sums_path) != manifest["sha256sums_sha256"]:
        errors.append("SHA256SUMS hash mismatch")
    if errors:
        raise RuntimeError("; ".join(errors))
    return {
        "zip_sha256": sha256(output),
        "zip_member_count": len(names),
        "payload_count": len(declared),
        "safe_extract": True,
        "crc": "PASS",
        "manifest": "PASS",
        "missing": 0,
        "mismatch": 0,
        "undeclared": 0,
        "duplicates": 0,
        "extracted_root": str(destination),
        "manifest_sha256": sha256(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("review/releases/CDH_D02_001_REVIEW.zip"))
    parser.add_argument("--extract-to", type=Path, default=Path("review/D02/verify_extracted"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    extract_to = args.extract_to if args.extract_to.is_absolute() else root / args.extract_to
    built = build(root, output)
    validation = validate_and_extract(output, extract_to)
    print(json.dumps({"build": built, "validation": validation}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
