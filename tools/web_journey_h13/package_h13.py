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
NAME = "CDH_H_R13_001_REVIEW"
PREFIX = f"{NAME}/"
H13 = ROOT / "review" / "H13"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
RESULT = H13 / "PACKAGE_RESULT.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (2026, 11, 6, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16; info.create_system = 3; return info


def payload_files() -> list[tuple[str, Path]]:
    mapped: dict[str, Path] = {}
    report_root = ROOT / "reports" / "H13"
    for source in report_root.rglob("*"):
        if source.is_file(): mapped[f"reports/{source.relative_to(report_root).as_posix()}"] = source
    evidence_root = H13 / "evidence"
    for source in evidence_root.rglob("*"):
        if source.is_file(): mapped[f"evidence/{source.relative_to(evidence_root).as_posix()}"] = source
    mapped["evidence/attempt1/ACTUAL_H13_BROWSER_HTTP.json"] = H13 / "attempt1_harness_tdz" / "ACTUAL_H13_BROWSER_HTTP.json"
    for name in ("INPUT_READBACK.json", "STAGED_PROJECT.json", "STATUS.json", "FINAL_VERIFICATION.json"):
        mapped[f"provenance/{name}"] = H13 / name
    mapped["tests/web/journey_h13/test_h13.py"] = ROOT / "tests" / "web" / "journey_h13" / "test_h13.py"
    tool_root = ROOT / "tools" / "web_journey_h13"
    for source in tool_root.iterdir():
        if source.is_file() and source.suffix.lower() in {".py", ".mjs"}: mapped[f"tools/{source.name}"] = source
    missing = [name for name, source in mapped.items() if not source.is_file()]
    if missing: raise FileNotFoundError(f"missing H13 payloads: {missing}")
    return sorted(mapped.items(), key=lambda item: item[0].casefold())


def verify(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip(); infos = archive.infolist(); names = [item.filename for item in infos]
        manifest = json.loads(archive.read(PREFIX + "MANIFEST.json")); mismatches = []
        for item in manifest["payloads"]:
            try: data = archive.read(PREFIX + item["path"])
            except KeyError: mismatches.append(item["path"]); continue
            if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]: mismatches.append(item["path"])
        declared = {PREFIX + "MANIFEST.json"} | {PREFIX + item["path"] for item in manifest["payloads"]}
        return {
            "entries": len(names), "payloads": len(manifest["payloads"]), "crc": "PASS" if bad is None else "FAIL",
            "mismatch": len(mismatches), "undeclared": len(set(names) - declared), "missing": len(declared - set(names)),
            "duplicates": len(names) - len(set(names)), "case_collisions": len(names) - len({name.casefold() for name in names}),
            "unsafe_paths": sum("\\" in name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names),
            "symlinks": sum(stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF) for item in infos),
        }


def main() -> None:
    if RELEASE.exists() or UPLOAD.exists(): raise RuntimeError("immutable H13 delivery already exists")
    final = json.loads((H13 / "FINAL_VERIFICATION.json").read_text(encoding="utf-8"))
    if final["status"] != "FAIL_H_TEST_STALE_RESULT_RACE" or final["portable_evidence_test_status"] != "PASS": raise RuntimeError("H13 evidence verification is not ready")
    files = payload_files()
    if any(".vitest-temp" in PurePosixPath(name).parts or "__pycache__" in PurePosixPath(name).parts or "runtime" in PurePosixPath(name).parts for name, _ in files): raise RuntimeError("runtime or cache entered H13 package")
    patterns = [re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"sk-[A-Za-z0-9_-]{20,}"), re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")]
    hits = [name for name, source in files if source.suffix.lower() not in {".png", ".sqlite3"} and any(pattern.search(source.read_bytes()) for pattern in patterns)]
    if hits: raise RuntimeError(f"secret scan failed: {hits}")
    payloads = [{"path": name, "bytes": source.stat().st_size, "sha256": sha256(source)} for name, source in files]
    manifest = {
        "schema_version": "CDH-REVIEW-MANIFEST-1", "delivery_type": "REVIEW", "task_id": "CDH-H13-LOCAL-TRIAL-FIRST-USE-001",
        "workline": "H", "revision": "INITIAL", "status": "READY_FOR_REVIEW", "product_status": "FAIL_H_TEST_STALE_RESULT_RACE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "a17_sha256": "5de6b85e72767e8135b7ff0e6e3acb534965d5f636f61eea918cb082b02a8237",
        "runtime_manifest_sha256": "b75814678c51490cfcb00e60b80f46e7c22e40af95118796bae1f856a6f1a176",
        "browser_attempt_count": 2, "browser_test_exit_code": 1, "chrome_process_exit_code": "UNKNOWN",
        "portable_evidence_test_pass_count": 16, "portable_evidence_test_count": 16,
        "launcher_negative_gate_pass_count": 2, "launcher_negative_gate_count": 2,
        "contains_synthetic_sqlite_evidence": True, "real_private_database_packaging_authorized": False,
        "production_affiliate_authorized": False, "production_deployment_authorized": False,
        "payload_count": len(payloads), "payloads": payloads,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    RELEASE.parent.mkdir(parents=True, exist_ok=True); UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, source in files: archive.writestr(zip_info(PREFIX + name), source.read_bytes())
        archive.writestr(zip_info(PREFIX + "MANIFEST.json"), manifest_bytes)
    shutil.copyfile(RELEASE, UPLOAD); release_sha, upload_sha = sha256(RELEASE), sha256(UPLOAD); integrity = verify(RELEASE)
    with tempfile.TemporaryDirectory(prefix="h13-replay-", dir=H13) as temporary:
        with zipfile.ZipFile(RELEASE) as archive: archive.extractall(temporary)
        replay_mismatch = 0
        for item in manifest["payloads"]:
            replay = Path(temporary) / NAME / Path(*PurePosixPath(item["path"]).parts)
            replay_mismatch += not (replay.is_file() and replay.stat().st_size == item["bytes"] and sha256(replay) == item["sha256"])
    clean = ("mismatch", "undeclared", "missing", "duplicates", "case_collisions", "unsafe_paths", "symlinks")
    identical = release_sha == upload_sha and RELEASE.read_bytes() == UPLOAD.read_bytes()
    ok = identical and integrity["crc"] == "PASS" and all(integrity[key] == 0 for key in clean) and replay_mismatch == 0
    result = {
        "task_id": "CDH-H13-LOCAL-TRIAL-FIRST-USE-001", "workline": "H", "delivery_type": "REVIEW", "delivery_status": "READY_FOR_REVIEW",
        "product_status": "FAIL_H_TEST_STALE_RESULT_RACE", "release": RELEASE.relative_to(ROOT).as_posix(), "upload_copy": UPLOAD.relative_to(ROOT).as_posix(),
        "release_sha256": release_sha, "upload_sha256": upload_sha, "identical_copy": identical,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "integrity": integrity, "extracted_replay_mismatch": replay_mismatch,
        "secret_pattern_hits": hits, "test_cache_count": 0, "artifact_integrity_status": "PASS" if ok else "FAIL",
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False)); raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
