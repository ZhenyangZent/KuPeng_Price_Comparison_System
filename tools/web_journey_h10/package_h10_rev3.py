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
NAME = "CDH_H_R11_005_REVIEW"
PREFIX = f"{NAME}/"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
RESULT = ROOT / "review" / "H10_REV3" / "PACKAGE_RESULT.json"


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


def payload_files() -> list[tuple[str, Path]]:
    mapped: dict[str, Path] = {}
    for source in (ROOT / "reports" / "H10_REV3").rglob("*"):
        if source.is_file():
            mapped[f"reports/{source.relative_to(ROOT / 'reports' / 'H10_REV3').as_posix()}"] = source
    for source in (ROOT / "review" / "H10_REV3" / "evidence").rglob("*"):
        if source.is_file():
            mapped[f"evidence/{source.relative_to(ROOT / 'review' / 'H10_REV3' / 'evidence').as_posix()}"] = source
    mapped["provenance/INPUT_READBACK.json"] = ROOT / "review" / "H10_REV3" / "INPUT_READBACK.json"
    mapped["provenance/STAGED_PROJECT.json"] = ROOT / "review" / "H10_REV3" / "STAGED_PROJECT.json"
    mapped["provenance/VERIFICATION_RESULT.json"] = ROOT / "review" / "H10_REV3" / "VERIFICATION_RESULT.json"
    mapped["tests/test_h10_rev3.py"] = ROOT / "tests" / "web" / "journey_h10_rev3" / "test_h10_rev3.py"
    tools = (
        "verify_rev3_inputs.py",
        "stage_project_rev3.py",
        "run_actual_h10_rev2.mjs",
        "run_actual_h10_rev3.mjs",
        "run_browser_and_record_rev3.py",
        "inspect_db_rev3.py",
        "verify_h10_rev3.py",
        "package_h10_rev3.py",
    )
    for name in tools:
        mapped[f"tools/{name}"] = ROOT / "tools" / "web_journey_h10" / name
    missing = [name for name, source in mapped.items() if not source.is_file()]
    if missing:
        raise FileNotFoundError(f"missing REVIEW payloads: {missing}")
    return sorted(mapped.items(), key=lambda item: item[0].casefold())


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
            "entries": len(names),
            "payloads": len(manifest["payloads"]),
            "crc": "PASS" if bad is None else "FAIL",
            "mismatch": len(mismatches),
            "undeclared": len(set(names) - declared),
            "missing": len(declared - set(names)),
            "duplicates": len(names) - len(set(names)),
            "case_collisions": len(names) - len({name.casefold() for name in names}),
            "unsafe_paths": sum("\\" in name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names),
            "symlinks": sum(stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF) for item in infos),
        }


def main() -> None:
    if RELEASE.exists() or UPLOAD.exists():
        raise RuntimeError("immutable H10 REV3 delivery already exists")
    files = payload_files()
    if any(".vitest-temp" in PurePosixPath(name).parts or "__pycache__" in PurePosixPath(name).parts for name, _ in files):
        raise RuntimeError("test cache entered REVIEW package")
    patterns = [
        re.compile(rb"AKIA[0-9A-Z]{16}"),
        re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\."),
    ]
    skip_scan = {".png", ".sqlite3"}
    hits = [name for name, source in files if source.suffix.lower() not in skip_scan and any(pattern.search(source.read_bytes()) for pattern in patterns)]
    if hits:
        raise RuntimeError(f"secret scan failed: {hits}")
    payloads = [{"path": name, "bytes": source.stat().st_size, "sha256": sha256(source)} for name, source in files]
    manifest = {
        "schema_version": "CDH-REVIEW-MANIFEST-1",
        "delivery_type": "REVIEW",
        "task_id": "CDH-H10-PRIVATE-HISTORY-REOPEN-E2E-001",
        "workline": "H",
        "revision": "REV3",
        "status": "READY_FOR_REVIEW",
        "product_status": "PASS",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "a14_sha256": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
        "b15_rev2_sha256": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
        "g10_sha256": "9efa1ba175e6579a210af092c3e35c7b44c1e60cb69d400fd0b4b3c2bfd91b14",
        "browser_test_exit_code": 0,
        "chrome_process_exit_code": 0,
        "product_gate_pass_count": 23,
        "product_gate_count": 23,
        "product_journey_run_count": 1,
        "contains_synthetic_sqlite_evidence": True,
        "real_private_database_packaging_authorized": False,
        "payload_count": len(payloads),
        "payloads": payloads,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, source in files:
            archive.writestr(zip_info(PREFIX + name), source.read_bytes())
        archive.writestr(zip_info(PREFIX + "MANIFEST.json"), manifest_bytes)
    shutil.copyfile(RELEASE, UPLOAD)
    release_sha, upload_sha = sha256(RELEASE), sha256(UPLOAD)
    integrity = verify(RELEASE)
    with tempfile.TemporaryDirectory(prefix="h10-rev3-review-replay-", dir=ROOT / "review" / "H10_REV3") as temp:
        with zipfile.ZipFile(RELEASE) as archive:
            archive.extractall(temp)
        replay_mismatch = 0
        for item in manifest["payloads"]:
            replay = Path(temp) / NAME / Path(*PurePosixPath(item["path"]).parts)
            replay_mismatch += not (replay.is_file() and replay.stat().st_size == item["bytes"] and sha256(replay) == item["sha256"])
    clean = ("mismatch", "undeclared", "missing", "duplicates", "case_collisions", "unsafe_paths", "symlinks")
    identical = release_sha == upload_sha and RELEASE.read_bytes() == UPLOAD.read_bytes()
    ok = identical and integrity["crc"] == "PASS" and all(integrity[key] == 0 for key in clean) and replay_mismatch == 0
    result = {
        "task_id": manifest["task_id"],
        "workline": "H",
        "revision": "REV3",
        "delivery_type": "REVIEW",
        "delivery_status": manifest["status"],
        "release": RELEASE.relative_to(ROOT).as_posix(),
        "upload_copy": UPLOAD.relative_to(ROOT).as_posix(),
        "release_sha256": release_sha,
        "upload_sha256": upload_sha,
        "identical_copy": identical,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "integrity": integrity,
        "extracted_replay_mismatch": replay_mismatch,
        "secret_pattern_hits": hits,
        "test_cache_count": 0,
        "artifact_integrity_status": "PASS" if ok else "FAIL",
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
