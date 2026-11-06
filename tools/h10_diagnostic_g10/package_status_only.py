from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path


PACKAGE = "CDH_G10_H10_LOOPBACK_DIAGNOSTIC_STATUS_ONLY"
SOURCES = {
    "STATUS.json": Path("reports/G10/STATUS_ONLY/STATUS.json"),
    "SUMMARY.md": Path("reports/G10/STATUS_ONLY/SUMMARY.md"),
    "evidence/H10_DIAGNOSIS.json": Path("review/G10/H10_DIAGNOSIS.json"),
    "evidence/H10_LOOPBACK_DIAGNOSIS.md": Path("reports/G10/H10_LOOPBACK_DIAGNOSIS.md"),
    "evidence/h10_loopback_restricted.json": Path("reports/G10/h10_loopback_restricted.json"),
    "evidence/h10_loopback_approved.json": Path("reports/G10/h10_loopback_approved.json"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def package(root: Path) -> dict:
    root = root.resolve(); stage = root / "review" / "G10" / "status_only" / PACKAGE
    release = root / "review" / "releases" / f"{PACKAGE}.zip"; upload = root / "review" / "00_TO_UPLOAD" / release.name
    if stage.exists() or release.exists() or upload.exists(): raise FileExistsError("STATUS_ONLY artifact already exists; refusing duplicate or overwrite")
    stage.mkdir(parents=True); payloads = []
    for relative, source_relative in SOURCES.items():
        source = root / source_relative
        if not source.is_file(): raise FileNotFoundError(source)
        target = stage / relative; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
        payloads.append({"path": relative, "bytes": target.stat().st_size, "sha256": sha256(target)})
    manifest = {"schema_version": "CDH-STATUS-ONLY-MANIFEST-1", "package_type": "STATUS_ONLY", "task_id": "CDH-G10-H10-LOOPBACK-DIAGNOSTIC-001", "workline": "G", "payload_count": len(payloads), "payloads": sorted(payloads, key=lambda item: item["path"])}
    manifest_path = stage / "MANIFEST.json"; manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release.parent.mkdir(parents=True, exist_ok=True); upload.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in sorted(stage.rglob("*")):
            if not source.is_file(): continue
            info = zipfile.ZipInfo((Path(PACKAGE) / source.relative_to(stage)).as_posix(), date_time=(2026, 11, 6, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    shutil.copy2(release, upload)
    return {"release": str(release), "upload": str(upload), "sha256": sha256(release), "upload_sha256": sha256(upload), "manifest_sha256": sha256(manifest_path), "payload_count": len(payloads), "byte_identical": release.read_bytes() == upload.read_bytes()}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path.cwd()); args = parser.parse_args(); print(json.dumps(package(args.root), ensure_ascii=False, indent=2))
