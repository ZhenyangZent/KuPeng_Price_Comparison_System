from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from .audit import sha256_file


PACKAGE_NAME = "CDH_G03_001_REVIEW"
INCLUDE = (
    Path("tools/ci_web_g03"),
    Path("tests/ci_web_g03"),
    Path("docs/CI_PREVIEW/G03"),
    Path("reports/G03/STATUS.json"),
    Path("reports/G03/IMPLEMENTATION_SUMMARY.md"),
    Path("reports/G03/TEST_RESULTS.md"),
    Path("reports/G03/CHANGE_LIST.md"),
    Path("reports/G03/RISK_REGISTER.md"),
    Path("reports/G03/COMMANDS_AND_EXIT_CODES.md"),
    Path("reports/G03/CANDIDATE_MATRIX.json"),
    Path("reports/G03/CANDIDATE_MATRIX.html"),
    Path("reports/G03/evidence/canonical"),
)


def _files(root: Path):
    for requested in INCLUDE:
        source = root / requested
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for candidate in candidates:
            if not candidate.is_file() or "__pycache__" in candidate.parts or candidate.suffix == ".pyc":
                continue
            yield candidate, candidate.relative_to(root)


def package(root: Path) -> dict:
    root = root.resolve()
    package_root = root / "review" / "G03" / "package" / PACKAGE_NAME
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True)
    copied: list[Path] = []
    for source, relative in _files(root):
        target = package_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    payloads = []
    for target in sorted(copied):
        payloads.append({"path": target.relative_to(package_root).as_posix(), "bytes": target.stat().st_size, "sha256": sha256_file(target)})
    manifest = {"schema": "CDH-G03-REVIEW-MANIFEST-1", "task_id": "CDH-G03-REPRODUCIBLE-WEB-CI-001", "payload_count": len(payloads), "payloads": payloads}
    manifest_path = package_root / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release = root / "review" / "releases" / f"{PACKAGE_NAME}.zip"
    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in sorted(package_root.rglob("*")):
            if not source.is_file():
                continue
            relative = (Path(PACKAGE_NAME) / source.relative_to(package_root)).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2026, 11, 5, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    upload = root / "review" / "00_TO_UPLOAD" / release.name
    upload.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(release, upload)
    return {
        "release": str(release), "upload": str(upload), "sha256": sha256_file(release),
        "upload_sha256": sha256_file(upload), "manifest_sha256": sha256_file(manifest_path),
        "payload_count": len(payloads), "byte_identical": release.read_bytes() == upload.read_bytes(),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(package(args.root), ensure_ascii=False, indent=2))
