from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
NAME = "CDH_H_R07_001_REVIEW"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
RESULT = ROOT / "review" / "H05" / "PACKAGE_RESULT.json"
PREFIX = f"{NAME}/"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (2026, 11, 5, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def payload_files() -> list[Path]:
    files: set[Path] = set()
    for base in (ROOT / "tools" / "web_journey_h05", ROOT / "tests" / "web" / "journey_h05", ROOT / "reports" / "H05"):
        files.update(path for path in base.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() != ".pyc")
    files.add(ROOT / "review" / "H05" / "INPUT_READBACK.json")
    evidence = ROOT / "review" / "H05" / "evidence"
    files.update(path for path in evidence.rglob("*") if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix().casefold())


def verify_archive(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        infos = archive.infolist()
        names = [info.filename for info in infos]
        manifest = json.loads(archive.read(PREFIX + "MANIFEST.json"))
        mismatches = []
        for item in manifest["payloads"]:
            try:
                data = archive.read(PREFIX + item["path"])
            except KeyError:
                mismatches.append(item["path"])
                continue
            if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                mismatches.append(item["path"])
        declared = {PREFIX + "MANIFEST.json"} | {PREFIX + item["path"] for item in manifest["payloads"]}
        return {
            "entries": len(names),
            "payloads": len(manifest["payloads"]),
            "crc": "PASS" if bad is None else "FAIL",
            "mismatch": len(mismatches),
            "undeclared": len(set(names) - declared),
            "missing": len(declared - set(names)),
            "duplicates": len(names) - len(set(names)),
            "case_collisions": len(names) - len({name.casefold() for name in names}),
            "unsafe_paths": sum("\\" in name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names),
            "symlinks": sum(stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF) for info in infos),
        }


def main() -> None:
    if RELEASE.exists() or UPLOAD.exists():
        raise RuntimeError("immutable H05 delivery already exists")
    files = payload_files()
    payloads = [
        {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in files
    ]
    manifest = {
        "schema_version": "CDH-H05-R07-REVIEW-MANIFEST-1",
        "task_id": "CDH-H05-REAL-A10-B11-BROWSER-JOURNEY-001",
        "authority": "AUTHORIZED_OFFLINE_R07_H_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_r07_sha256": "76b1332c3e2cd82a05e5f26e6d3e0c01cdf65e828f82d5b586902bdfacda2827",
        "a09_sha256": "96d239e4a3bb5ca57624c0b8d6e06344ad68b6482b13d8ee9b72a8f1997ebbde",
        "b10_sha256": "dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549",
        "a10_state": "NOT_AVAILABLE",
        "b11_state": "NOT_AVAILABLE",
        "status": "READY_FOR_REVIEW_A09_B10_BLOCKER_REPRODUCED_A10_B11_NOT_RUN",
        "exact_a09_b10_integration": "FAIL_INCOMPATIBLE_NO_UI_FETCH",
        "exact_a10_b11_integration": "NOT_RUN_INPUT_UNAVAILABLE",
        "payload_count": len(payloads),
        "payloads": payloads,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.writestr(zip_info(PREFIX + path.relative_to(ROOT).as_posix()), path.read_bytes())
        archive.writestr(zip_info(PREFIX + "MANIFEST.json"), manifest_bytes)
    shutil.copyfile(RELEASE, UPLOAD)

    integrity = verify_archive(RELEASE)
    release_sha = sha256(RELEASE)
    upload_sha = sha256(UPLOAD)
    with tempfile.TemporaryDirectory(prefix="h05-replay-", dir=ROOT / "review" / "H05") as temp:
        with zipfile.ZipFile(RELEASE) as archive:
            archive.extractall(temp)
        replay_mismatch = 0
        for item in manifest["payloads"]:
            path = Path(temp) / NAME / Path(*PurePosixPath(item["path"]).parts)
            replay_mismatch += not (path.is_file() and path.stat().st_size == item["bytes"] and sha256(path) == item["sha256"])

    clean_keys = ("mismatch", "undeclared", "missing", "duplicates", "case_collisions", "unsafe_paths", "symlinks")
    ok = (
        release_sha == upload_sha
        and RELEASE.read_bytes() == UPLOAD.read_bytes()
        and integrity["crc"] == "PASS"
        and all(integrity[key] == 0 for key in clean_keys)
        and replay_mismatch == 0
    )
    result = {
        "task_id": manifest["task_id"],
        "release": RELEASE.relative_to(ROOT).as_posix(),
        "upload_copy": UPLOAD.relative_to(ROOT).as_posix(),
        "release_sha256": release_sha,
        "upload_sha256": upload_sha,
        "identical_copy": release_sha == upload_sha and RELEASE.read_bytes() == UPLOAD.read_bytes(),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "integrity": integrity,
        "extracted_replay_mismatch": replay_mismatch,
        "status": "PASS" if ok else "FAIL",
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
