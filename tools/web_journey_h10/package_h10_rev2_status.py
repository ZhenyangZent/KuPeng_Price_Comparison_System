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
NAME = "CDH_H_R11_004_STATUS_ONLY"
PREFIX = f"{NAME}/"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
RESULT = ROOT / "review" / "H10_REV2" / "PACKAGE_RESULT.json"


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
    mapped: dict[str, Path] = {
        "STATUS.json": ROOT / "review" / "H10_REV2" / "STATUS.json",
        "SUMMARY.md": ROOT / "review" / "H10_REV2" / "SUMMARY.md",
        "provenance/G10_INPUT_READBACK.json": ROOT / "review" / "H10_REV2" / "G10_INPUT_READBACK.json",
        "provenance/STAGED_PROJECT.json": ROOT / "review" / "H10_REV2" / "STAGED_PROJECT.json",
        "upstream/G10/H10_LOOPBACK_DIAGNOSIS.md": ROOT / "reports" / "G10" / "H10_LOOPBACK_DIAGNOSIS.md",
        "upstream/G10/h10_loopback_approved.json": ROOT / "reports" / "G10" / "h10_loopback_approved.json",
        "upstream/G10/h10_loopback_restricted.json": ROOT / "reports" / "G10" / "h10_loopback_restricted.json",
    }
    for source in (ROOT / "review" / "H10_REV2" / "evidence").rglob("*"):
        if source.is_file():
            mapped[f"evidence/{source.relative_to(ROOT / 'review' / 'H10_REV2' / 'evidence').as_posix()}"] = source
    for name in ("verify_g10_rev2.py", "stage_project_rev2.py", "run_actual_h10_rev2.mjs", "run_browser_and_record_rev2.py", "inspect_db_rev2.py"):
        mapped[f"tools/{name}"] = ROOT / "tools" / "web_journey_h10" / name
    missing = [name for name, source in mapped.items() if not source.is_file()]
    if missing:
        raise FileNotFoundError(f"missing STATUS_ONLY payloads: {missing}")
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
            "entries": len(names), "payloads": len(manifest["payloads"]), "crc": "PASS" if bad is None else "FAIL",
            "mismatch": len(mismatches), "undeclared": len(set(names) - declared), "missing": len(declared - set(names)),
            "duplicates": len(names) - len(set(names)), "case_collisions": len(names) - len({name.casefold() for name in names}),
            "unsafe_paths": sum("\\" in name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names),
            "symlinks": sum(stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF) for item in infos),
        }


def main() -> None:
    if RELEASE.exists() or UPLOAD.exists():
        raise RuntimeError("immutable H10 REV2 STATUS_ONLY delivery already exists")
    files = payload_files()
    if any(".vitest-temp" in PurePosixPath(name).parts for name, _ in files):
        raise RuntimeError(".vitest-temp entered STATUS_ONLY package")
    patterns = [re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"sk-[A-Za-z0-9_-]{20,}"), re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")]
    hits = [name for name, source in files if source.suffix.lower() not in {".png", ".sqlite3"} and any(pattern.search(source.read_bytes()) for pattern in patterns)]
    if hits:
        raise RuntimeError(f"secret scan failed: {hits}")
    payloads = [{"path": name, "bytes": source.stat().st_size, "sha256": sha256(source)} for name, source in files]
    manifest = {
        "schema_version": "CDH-STATUS-ONLY-MANIFEST-1",
        "delivery_type": "STATUS_ONLY",
        "task_id": "CDH-H10-PRIVATE-HISTORY-REOPEN-E2E-001",
        "workline": "H",
        "revision": "REV2",
        "status": "FAIL_BROWSER_ASSERTION_FORMAT_MISMATCH",
        "supersedes_zip": "CDH_H_R11_003_STATUS_ONLY.zip",
        "supersedes_sha256": "cf73ce1978fa4753fa2a308fc31e7d16a8da6786a6f8ed5121bfb369e8cf7fda",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "a14_sha256": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
        "b15_rev2_sha256": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
        "browser_test_exit_code": 1,
        "chrome_process_exit_code": 0,
        "central_action_required": True,
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
    with tempfile.TemporaryDirectory(prefix="h10-rev2-status-replay-", dir=ROOT / "review" / "H10_REV2") as temp:
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
        "task_id": manifest["task_id"], "workline": "H", "revision": "REV2", "delivery_type": "STATUS_ONLY",
        "delivery_status": manifest["status"], "release": RELEASE.relative_to(ROOT).as_posix(), "upload_copy": UPLOAD.relative_to(ROOT).as_posix(),
        "release_sha256": release_sha, "upload_sha256": upload_sha, "identical_copy": identical,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "integrity": integrity,
        "extracted_replay_mismatch": replay_mismatch, "secret_pattern_hits": hits, "vitest_temp_count": 0,
        "artifact_integrity_status": "PASS" if ok else "FAIL",
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
