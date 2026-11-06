from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
NAME = "CDH_D_R12_002_REVIEW"
STAGE_PARENT = ROOT / "review" / "D13" / "002" / "package"
STAGE = STAGE_PARENT / NAME
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
INPUTS = {
    ROOT / "review/releases/CDH_B_R12_002_REVIEW.zip": "6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6",
    ROOT / "review/releases/CDH_D_R12_001_REVIEW.zip": "eeb7b434db360818399414133cdb9e173654ea6850ea0a76ac702a626f806d2f",
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
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for source in sorted((ROOT / "tools/web_security_d13_rev2").glob("*.py")):
        copy(source, f"tools/web_security_d13_rev2/{source.name}")
    for source in sorted((ROOT / "reports/D13_REV2").iterdir()):
        if source.is_file():
            copy(source, f"reports/D13_REV2/{source.name}")
    for source in sorted((ROOT / "review/D13/002/evidence").iterdir()):
        if source.is_file():
            copy(source, f"review/D13/002/evidence/{source.name}")
    precheck = ROOT / "review/D13/002/precheck/A15_BOUNDARY_PRECHECK.json"
    copy(precheck, "review/D13/002/precheck/A15_BOUNDARY_PRECHECK.json")
    extracted = ROOT / "review/D13/002/input/CDH_B_R12_002_REVIEW"
    for source in sorted(extracted.rglob("*")):
        if source.is_file() and "__pycache__" not in source.parts and source.suffix not in {".pyc", ".pyo"}:
            copy(source, f"review/D13/002/input/CDH_B_R12_002_REVIEW/{source.relative_to(extracted).as_posix()}")
    for source in INPUTS:
        copy(source, f"inputs/{source.name}")
    payloads = []
    for path in sorted(STAGE.rglob("*")):
        if path.is_file():
            payloads.append({"path": f"{NAME}/{path.relative_to(STAGE).as_posix()}", "bytes": path.stat().st_size, "sha256": sha(path)})
    manifest = {"schema_version": "CDH-D13-REV2-REVIEW-MANIFEST-1", "task_id": "CDH-D13-B16-BATCH-IMPORT-SECURITY", "status": "FAIL_MID_TRANSACTION_FRESH_PREVIEW_RECOVERY", "subject": {"filename": "CDH_B_R12_002_REVIEW.zip", "sha256": INPUTS[ROOT / "review/releases/CDH_B_R12_002_REVIEW.zip"]}, "original_d13": {"filename": "CDH_D_R12_001_REVIEW.zip", "sha256": INPUTS[ROOT / "review/releases/CDH_D_R12_001_REVIEW.zip"]}, "b_source_modified": False, "payloads": payloads}
    (STAGE / "REVIEW_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if RELEASE.exists() or UPLOAD.exists():
        raise RuntimeError("refusing to overwrite D13 REV2 delivery")
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, f"{NAME}/{path.relative_to(STAGE).as_posix()}")
    shutil.copy2(RELEASE, UPLOAD)
    result = {"release": str(RELEASE), "upload": str(UPLOAD), "sha256": sha(RELEASE), "upload_sha256": sha(UPLOAD), "manifest_sha256": sha(STAGE / "REVIEW_MANIFEST.json"), "payload_count": len(payloads)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["sha256"] == result["upload_sha256"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
