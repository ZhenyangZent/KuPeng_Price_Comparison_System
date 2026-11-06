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
NAME = "CDH_H_R08_001_REVIEW"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
RESULT = ROOT / "review" / "H06" / "PACKAGE_RESULT.json"
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
    for base in (ROOT / "tools" / "web_journey_h06", ROOT / "tests" / "web" / "journey_h06", ROOT / "reports" / "H06"):
        files.update(path for path in base.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() != ".pyc")
    files.add(ROOT / "review" / "H06" / "INPUT_READBACK.json")
    evidence = ROOT / "review" / "H06" / "evidence"
    files.update(path for path in evidence.rglob("*") if path.is_file() and path.name != "RUN_FAILURE.json" and not path.name.startswith("run-failure"))
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
            "entries": len(names), "payloads": len(manifest["payloads"]), "crc": "PASS" if bad is None else "FAIL",
            "mismatch": len(mismatches), "undeclared": len(set(names) - declared), "missing": len(declared - set(names)),
            "duplicates": len(names) - len(set(names)), "case_collisions": len(names) - len({name.casefold() for name in names}),
            "unsafe_paths": sum("\\" in name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names),
            "symlinks": sum(stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF) for info in infos),
        }


def main() -> None:
    if RELEASE.exists() or UPLOAD.exists():
        raise RuntimeError("immutable H06 delivery already exists")
    files = payload_files()
    payloads = [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in files]
    manifest = {
        "schema_version": "CDH-H06-R08-REVIEW-MANIFEST-1",
        "task_id": "CDH-H06-A10-B11-ACTUAL-BROWSER-001",
        "authority": "AUTHORIZED_OFFLINE_R08_H_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_r08_sha256": "61d75b334fd7073202691bab887186261c85d1fa42af05e79f16d1a46f24b144",
        "a10_sha256_observed": "eb4b449972f1bb6bccd9457e8ee88a2b3c69f2a2001b17fc5adfceb23c6a7e08",
        "a10_central_ack_state": "NOT_ACKNOWLEDGED_IN_R08_AUTHORITY",
        "b11_sha256": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
        "status": "READY_FOR_REVIEW_PROVISIONAL_A10_B11_EVIDENCE_AWAITING_A10_ACK",
        "actual_browser_evidence": "PASS_PROVISIONAL_EVIDENCE",
        "final_integration_gate": "PROVISIONAL_PASS_AWAITING_CENTRAL_A10_SHA_ACK",
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
    with tempfile.TemporaryDirectory(prefix="h06-replay-", dir=ROOT / "review" / "H06") as temp:
        with zipfile.ZipFile(RELEASE) as archive:
            archive.extractall(temp)
        replay_mismatch = 0
        for item in manifest["payloads"]:
            replay = Path(temp) / NAME / Path(*PurePosixPath(item["path"]).parts)
            replay_mismatch += not (replay.is_file() and replay.stat().st_size == item["bytes"] and sha256(replay) == item["sha256"])
    clean = ("mismatch", "undeclared", "missing", "duplicates", "case_collisions", "unsafe_paths", "symlinks")
    ok = release_sha == upload_sha and RELEASE.read_bytes() == UPLOAD.read_bytes() and integrity["crc"] == "PASS" and all(integrity[key] == 0 for key in clean) and replay_mismatch == 0
    result = {
        "task_id": manifest["task_id"], "release": RELEASE.relative_to(ROOT).as_posix(), "upload_copy": UPLOAD.relative_to(ROOT).as_posix(),
        "release_sha256": release_sha, "upload_sha256": upload_sha, "identical_copy": release_sha == upload_sha and RELEASE.read_bytes() == UPLOAD.read_bytes(),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "integrity": integrity, "extracted_replay_mismatch": replay_mismatch,
        "status": "PASS" if ok else "FAIL",
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
