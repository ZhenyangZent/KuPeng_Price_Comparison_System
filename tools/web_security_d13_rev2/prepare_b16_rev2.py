from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "review" / "releases" / "CDH_B_R12_002_REVIEW.zip"
EXPECTED_SHA256 = "6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6"
PACKAGE = "CDH_B_R12_002_REVIEW"
DESTINATION = ROOT / "review" / "D13" / "002" / "input" / PACKAGE
EXPECTED_INPUTS = {
    "A15": {"file": "CDH_A_R12_001_REVIEW.zip", "sha256": "5cc44dedd910ff9b2055cfc2772ad0c3d6db627ffc818794f81fd3d9b5552d4b"},
    "B16_REV1": {"file": "CDH_B_R12_001_REVIEW.zip", "sha256": "d2149952fe1693381f74ac639a770b393b8703a368df68eea990cd5e231cf23b"},
    "D13": {"file": "CDH_D_R12_001_REVIEW.zip", "sha256": "eeb7b434db360818399414133cdb9e173654ea6850ea0a76ac702a626f806d2f"},
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe(name: str) -> bool:
    value = PurePosixPath(name)
    return bool(name) and not value.is_absolute() and ".." not in value.parts and "\\" not in name and "\x00" not in name


def main() -> int:
    archive_sha = file_digest(ARCHIVE)
    if archive_sha != EXPECTED_SHA256:
        raise RuntimeError("B16 REV2 archive SHA-256 mismatch")
    with zipfile.ZipFile(ARCHIVE) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if archive.testzip() is not None:
            raise RuntimeError("B16 REV2 CRC failure")
        if any(not safe(name) for name in names):
            raise RuntimeError("unsafe archive member")
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise RuntimeError("duplicate archive member")
        if any(((item.external_attr >> 16) & 0o170000) == 0o120000 for item in infos):
            raise RuntimeError("archive contains a link")
        manifest_name = f"{PACKAGE}/REVIEW_MANIFEST.json"
        manifest_data = archive.read(manifest_name)
        manifest = json.loads(manifest_data)
        if (
            manifest.get("schema_version") != "CDH-B16-REV2-REVIEW-MANIFEST-1"
            or manifest.get("task_id") != "CDH-B16-PRIVATE-BATCH-IMPORT-001"
            or manifest.get("revision") != "REV2"
            or manifest.get("inputs") != EXPECTED_INPUTS
            or manifest.get("api_route_or_request_schema_change_count") != 0
        ):
            raise RuntimeError("B16 REV2 authority or compatibility mismatch")
        declared = {item["path"]: item for item in manifest["payloads"]}
        actual = set(names) - {manifest_name}
        if set(declared) != actual:
            raise RuntimeError("B16 REV2 manifest path mismatch")
        for name, item in declared.items():
            data = archive.read(name)
            if len(data) != item["bytes"] or digest(data) != item["sha256"]:
                raise RuntimeError(f"B16 REV2 manifest payload mismatch: {name}")
        parent = DESTINATION.parent.resolve()
        destination = DESTINATION.resolve()
        if not destination.is_relative_to(parent) or destination == parent:
            raise RuntimeError("unsafe extraction destination")
        if DESTINATION.exists():
            shutil.rmtree(DESTINATION)
        DESTINATION.mkdir(parents=True)
        prefix = f"{PACKAGE}/"
        for info in infos:
            if info.filename == manifest_name:
                target = DESTINATION / "REVIEW_MANIFEST.json"
            else:
                if not info.filename.startswith(prefix):
                    raise RuntimeError("archive member outside package prefix")
                target = DESTINATION / PurePosixPath(info.filename[len(prefix):])
            if not target.resolve().is_relative_to(destination):
                raise RuntimeError("extraction target escaped destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    result = {
        "schema_version": "CDH-D13-B16-REV2-INPUT-VERIFICATION-1",
        "archive": ARCHIVE.name,
        "archive_sha256": archive_sha,
        "manifest_sha256": digest(manifest_data),
        "manifest_payload_count": len(declared),
        "crc": "PASS",
        "missing": 0,
        "mismatch": 0,
        "undeclared": 0,
        "duplicates": 0,
        "unsafe_paths": 0,
        "links": 0,
        "api_route_or_request_schema_change_count": 0,
        "extracted_to": str(DESTINATION),
    }
    output = ROOT / "review" / "D13" / "002" / "evidence" / "INPUT_VERIFICATION.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
