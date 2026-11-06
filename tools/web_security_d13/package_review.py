from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAME = "CDH_D_R12_001_REVIEW"
STAGE_PARENT = ROOT / "review" / "D13" / "001" / "package"
STAGE = STAGE_PARENT / PACKAGE_NAME
RELEASE = ROOT / "review" / "releases" / f"{PACKAGE_NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{PACKAGE_NAME}.zip"
B16_ZIP = ROOT / "review" / "releases" / "CDH_B_R12_001_REVIEW.zip"
B16_EXTRACTED = ROOT / "review" / "D13" / "001" / "input" / "CDH_B_R12_001_REVIEW"
EXPECTED_B16_SHA256 = "d2149952fe1693381f74ac639a770b393b8703a368df68eea990cd5e231cf23b"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_stage_reset() -> None:
    stage = STAGE.resolve()
    parent = STAGE_PARENT.resolve()
    if not stage.is_relative_to(parent) or stage == parent:
        raise RuntimeError("unsafe stage target")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)


def copy_file(source: Path, relative: str) -> None:
    target = STAGE / PurePosixPath(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> int:
    if not B16_ZIP.is_file() or sha256(B16_ZIP) != EXPECTED_B16_SHA256:
        raise RuntimeError("exact B16 input is unavailable")
    safe_stage_reset()
    for source in sorted((ROOT / "tools" / "web_security_d13").glob("*.py")):
        copy_file(source, f"tools/web_security_d13/{source.name}")
    for source in sorted((ROOT / "reports" / "D13").iterdir()):
        if source.is_file():
            copy_file(source, f"reports/D13/{source.name}")
    for source in sorted((ROOT / "review" / "D13" / "001" / "evidence").iterdir()):
        if source.is_file():
            copy_file(source, f"review/D13/001/evidence/{source.name}")
    copy_file(B16_ZIP, f"inputs/{B16_ZIP.name}")
    for source in sorted(B16_EXTRACTED.rglob("*")):
        if source.is_file() and "__pycache__" not in source.parts and source.suffix not in {".pyc", ".pyo"}:
            relative = source.relative_to(B16_EXTRACTED).as_posix()
            copy_file(source, f"review/D13/001/input/CDH_B_R12_001_REVIEW/{relative}")
    payloads = []
    for path in sorted(STAGE.rglob("*")):
        if path.is_file():
            payloads.append(
                {
                    "path": f"{PACKAGE_NAME}/{path.relative_to(STAGE).as_posix()}",
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    manifest = {
        "schema_version": "CDH-D13-REVIEW-MANIFEST-1",
        "task_id": "CDH-D13-B16-BATCH-IMPORT-SECURITY",
        "status": "FAIL_ONE_TIME_CONFIRM_TOKEN_RACE",
        "subject": {"filename": B16_ZIP.name, "sha256": EXPECTED_B16_SHA256},
        "source_modified": False,
        "payloads": payloads,
    }
    (STAGE / "REVIEW_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    if RELEASE.exists() or UPLOAD.exists():
        raise RuntimeError("refusing to overwrite an existing D13 delivery")
    with zipfile.ZipFile(RELEASE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, f"{PACKAGE_NAME}/{path.relative_to(STAGE).as_posix()}")
    shutil.copy2(RELEASE, UPLOAD)
    result = {
        "release": str(RELEASE),
        "upload": str(UPLOAD),
        "sha256": sha256(RELEASE),
        "upload_sha256": sha256(UPLOAD),
        "manifest_sha256": sha256(STAGE / "REVIEW_MANIFEST.json"),
        "payload_count": len(payloads),
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["sha256"] == result["upload_sha256"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
