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
NAME = "CDH_H_R11_001_REVIEW"
RELEASE = ROOT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
RESULT = ROOT / "review" / "H09" / "PACKAGE_RESULT.json"
PREFIX = f"{NAME}/"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (2026, 11, 6, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16; info.create_system = 3
    return info


def payload_files() -> list[Path]:
    files: set[Path] = set()
    for base in (ROOT / "tools" / "web_journey_h09", ROOT / "tests" / "web" / "journey_h09", ROOT / "reports" / "H09"):
        files.update(path for path in base.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() != ".pyc")
    files.update((ROOT / "review" / "H09" / name) for name in ("INPUT_READBACK.json", "STAGED_PROJECT.json"))
    files.update(path for path in (ROOT / "review" / "H09" / "evidence").rglob("*") if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix().casefold())


def verify(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip(); infos = archive.infolist(); names = [item.filename for item in infos]
        manifest = json.loads(archive.read(PREFIX + "MANIFEST.json")); mismatches = []
        for item in manifest["payloads"]:
            try:
                data = archive.read(PREFIX + item["path"])
            except KeyError:
                mismatches.append(item["path"]); continue
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
        raise RuntimeError("immutable H09 delivery already exists")
    files = payload_files()
    patterns = [re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"sk-[A-Za-z0-9_-]{20,}"), re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")]
    hits = [path.relative_to(ROOT).as_posix() for path in files if path.suffix.lower() not in {".png", ".sqlite3"} and any(pattern.search(path.read_bytes()) for pattern in patterns)]
    if hits:
        raise RuntimeError(f"secret scan failed: {hits}")
    payloads = [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in files]
    manifest = {
        "schema_version": "CDH-H09-R11-REVIEW-MANIFEST-1",
        "task_id": "CDH-H09-A13REV3-B15REV2-WINDOWS-E2E-001",
        "authority": "R11_H09_EXACT_A13_REV3_B15_REV2_LOCAL_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "a13_rev3_sha256": "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274",
        "b15_rev2_sha256": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
        "status": "READY_FOR_REVIEW", "product_gate": "PASS_COMPLETE_WINDOWS_PRIVATE_OBSERVATION_E2E",
        "product_journey_run_count": 1, "payload_count": len(payloads), "payloads": payloads,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    RELEASE.parent.mkdir(parents=True, exist_ok=True); UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.writestr(zip_info(PREFIX + path.relative_to(ROOT).as_posix()), path.read_bytes())
        archive.writestr(zip_info(PREFIX + "MANIFEST.json"), manifest_bytes)
    shutil.copyfile(RELEASE, UPLOAD); release_sha = sha256(RELEASE); upload_sha = sha256(UPLOAD); integrity = verify(RELEASE)
    with tempfile.TemporaryDirectory(prefix="h09-replay-", dir=ROOT / "review" / "H09") as temp:
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
        "task_id": manifest["task_id"], "release": RELEASE.relative_to(ROOT).as_posix(), "upload_copy": UPLOAD.relative_to(ROOT).as_posix(),
        "release_sha256": release_sha, "upload_sha256": upload_sha, "identical_copy": identical,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "integrity": integrity,
        "extracted_replay_mismatch": replay_mismatch, "secret_pattern_hits": hits, "status": "PASS" if ok else "FAIL",
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
