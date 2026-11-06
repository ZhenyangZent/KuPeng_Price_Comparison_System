from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
NAME = "CDH_D_R12_003_REVIEW"
STAGE_PARENT = ROOT / "review" / "D13" / "003" / "package"
STAGE = STAGE_PARENT / NAME
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
INPUTS = {
    ROOT / "review/releases/CDH_B_R12_003_REVIEW.zip": "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
    ROOT / "review/releases/CDH_D_R12_002_REVIEW.zip": "dc72821516e2d7a726f8bfa72976db19f560621b75fb31d8d0440bc2a1bf256c",
}


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def copy(source: Path, relative: str) -> None:
    target = STAGE / PurePosixPath(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> int:
    for path, expected in INPUTS.items():
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"exact input unavailable: {path.name}")
    stage = STAGE.resolve()
    parent = STAGE_PARENT.resolve()
    if not stage.is_relative_to(parent) or stage == parent:
        raise RuntimeError("unsafe stage")
    if STAGE.exists() or RELEASE.exists() or UPLOAD.exists():
        raise RuntimeError("refusing to overwrite D13 REV3 delivery or stage")
    STAGE.mkdir(parents=True)
    for source in sorted((ROOT / "tools/web_security_d13_rev3").glob("*.py")):
        copy(source, f"tools/web_security_d13_rev3/{source.name}")
    for source in sorted((ROOT / "reports/D13_REV3").iterdir()):
        if source.is_file():
            copy(source, f"reports/D13_REV3/{source.name}")
    for source in sorted((ROOT / "review/D13/003/evidence").iterdir()):
        if source.is_file():
            copy(source, f"review/D13/003/evidence/{source.name}")
    extracted = ROOT / "review/D13/003/input/CDH_B_R12_003_REVIEW"
    for source in sorted(extracted.rglob("*")):
        if source.is_file() and "__pycache__" not in source.parts and source.suffix not in {".pyc", ".pyo"}:
            copy(source, f"review/D13/003/input/CDH_B_R12_003_REVIEW/{source.relative_to(extracted).as_posix()}")
    for source in INPUTS:
        copy(source, f"inputs/{source.name}")
    payloads = []
    for path in sorted(STAGE.rglob("*")):
        if path.is_file():
            payloads.append(
                {
                    "path": f"{NAME}/{path.relative_to(STAGE).as_posix()}",
                    "bytes": path.stat().st_size,
                    "sha256": sha(path),
                }
            )
    manifest = {
        "schema_version": "CDH-D13-REV3-REVIEW-MANIFEST-1",
        "task_id": "CDH-D13-B16-BATCH-IMPORT-SECURITY",
        "status": "D13_B16_REV3_SECURITY_RETEST_PASS",
        "subject": {
            "filename": "CDH_B_R12_003_REVIEW.zip",
            "sha256": INPUTS[ROOT / "review/releases/CDH_B_R12_003_REVIEW.zip"],
        },
        "prior_fail_evidence": {
            "filename": "CDH_D_R12_002_REVIEW.zip",
            "sha256": INPUTS[ROOT / "review/releases/CDH_D_R12_002_REVIEW.zip"],
        },
        "b_source_modified": False,
        "production_database_access_count": 0,
        "external_request_count": 0,
        "payloads": payloads,
    }
    (STAGE / "REVIEW_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, f"{NAME}/{path.relative_to(STAGE).as_posix()}")
    shutil.copy2(RELEASE, UPLOAD)
    result = {
        "release": str(RELEASE),
        "upload": str(UPLOAD),
        "sha256": sha(RELEASE),
        "upload_sha256": sha(UPLOAD),
        "manifest_sha256": sha(STAGE / "REVIEW_MANIFEST.json"),
        "payload_count": len(payloads),
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["sha256"] == result["upload_sha256"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
