from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
NAME = "CDH_H_R11_002_REVIEW"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
RESULT = ROOT / "review" / "H10" / "PACKAGE_RESULT.json"
PREFIX = f"{NAME}/"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (2026, 11, 6, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def payload_files() -> list[Path]:
    files: set[Path] = set()
    for base in (ROOT / "tools" / "web_journey_h10", ROOT / "reports" / "H10"):
        files.update(path for path in base.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() != ".pyc")
    files.update((ROOT / "review" / "H10" / name) for name in ("DEPENDENCY_STATUS.json", "INPUT_READBACK.json", "STAGED_PROJECT.json"))
    files.update(path for path in (ROOT / "review" / "H10" / "evidence").rglob("*") if path.is_file() and path.name != "BROWSER_PROCESS_RECEIPT.json")
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix().casefold())


def verify(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        infos = archive.infolist()
        names = [item.filename for item in infos]
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
            "symlinks": sum(stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF) for item in infos),
        }


def main() -> None:
    if RELEASE.exists() or UPLOAD.exists():
        raise RuntimeError("immutable H10 failure delivery already exists")
    files = payload_files()
    forbidden = [path.relative_to(ROOT).as_posix() for path in files if ".vitest-temp" in path.parts]
    if forbidden:
        raise RuntimeError(f"test cache entered package: {forbidden}")
    patterns = [re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"sk-[A-Za-z0-9_-]{20,}"), re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")]
    hits = [path.relative_to(ROOT).as_posix() for path in files if any(pattern.search(path.read_bytes()) for pattern in patterns)]
    if hits:
        raise RuntimeError(f"secret scan failed: {hits}")
    payloads = [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in files]
    manifest = {
        "schema_version": "CDH-H10-R11-FAILURE-REVIEW-MANIFEST-1",
        "task_id": "CDH-H10-PRIVATE-HISTORY-REOPEN-E2E-001",
        "authority": "R11_H10_EXACT_A14_B15_REV2_LOCAL_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "a14_sha256": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
        "b15_rev2_sha256": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
        "status": "ESCALATION_REQUIRED", "product_gate": "FAIL_SERVER_HEALTH_UNREACHABLE_BEFORE_BROWSER",
        "terminal_browser_process_exit_code": 1, "browser_started": False, "product_journey_run_count": 0,
        "payload_count": len(payloads), "payloads": payloads,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in files:
            archive.writestr(zip_info(PREFIX + source.relative_to(ROOT).as_posix()), source.read_bytes())
        archive.writestr(zip_info(PREFIX + "MANIFEST.json"), manifest_bytes)
    shutil.copyfile(RELEASE, UPLOAD)
    release_sha, upload_sha = sha256(RELEASE), sha256(UPLOAD)
    integrity = verify(RELEASE)
    with tempfile.TemporaryDirectory(prefix="h10-failure-replay-", dir=ROOT / "review" / "H10") as temp:
        with zipfile.ZipFile(RELEASE) as archive:
            archive.extractall(temp)
        replay_mismatch = 0
        for item in manifest["payloads"]:
            replay = Path(temp) / NAME / Path(*PurePosixPath(item["path"]).parts)
            replay_mismatch += not (replay.is_file() and replay.stat().st_size == item["bytes"] and sha256(replay) == item["sha256"])
    clean = ("mismatch", "undeclared", "missing", "duplicates", "case_collisions", "unsafe_paths", "symlinks")
    identical = release_sha == upload_sha and RELEASE.read_bytes() == UPLOAD.read_bytes()
    artifact_ok = identical and integrity["crc"] == "PASS" and all(integrity[key] == 0 for key in clean) and replay_mismatch == 0
    result = {
        "task_id": manifest["task_id"], "delivery_status": manifest["status"], "product_gate": manifest["product_gate"],
        "release": RELEASE.relative_to(ROOT).as_posix(), "upload_copy": UPLOAD.relative_to(ROOT).as_posix(),
        "release_sha256": release_sha, "upload_sha256": upload_sha, "identical_copy": identical,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "integrity": integrity,
        "extracted_replay_mismatch": replay_mismatch, "secret_pattern_hits": hits, "vitest_temp_count": 0,
        "artifact_integrity_status": "PASS" if artifact_ok else "FAIL",
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if artifact_ok else 1)


if __name__ == "__main__":
    main()
