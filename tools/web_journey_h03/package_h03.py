from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[2]
PACKAGE = "CDH_H03_001_REVIEW"
RELEASE = PROJECT / "review" / "releases" / f"{PACKAGE}.zip"
UPLOAD = PROJECT / "review" / "00_TO_UPLOAD" / f"{PACKAGE}.zip"
RESULT = PROJECT / "review" / "H03" / "PACKAGE_RESULT.json"
PREFIX = f"{PACKAGE}/"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_tree(files: set[Path], root: Path, *, exclude: set[str] | None = None) -> None:
    excluded = exclude or set()
    for path in root.rglob("*"):
        if path.is_file() and not any(part in excluded for part in path.parts):
            files.add(path)


def selected_files() -> list[Path]:
    files: set[Path] = set()
    add_tree(files, PROJECT / "tools" / "web_journey_h03", exclude={"__pycache__"})
    add_tree(files, PROJECT / "tests" / "web" / "journey_h03", exclude={"__pycache__"})
    add_tree(files, PROJECT / "reports" / "H03", exclude={"__pycache__"})
    files.add(PROJECT / "review" / "H03" / "BASELINE_READBACK.json")
    evidence = PROJECT / "review" / "H03" / "evidence"
    for name in (
        "H03_VERIFICATION.json",
        "BROWSER_JOURNEY.json",
        "NETWORK_HAR.json",
        "BROWSER_JOURNEY_A08_B09.json",
        "NETWORK_HAR_A08_B09.json",
    ):
        files.add(evidence / name)
    files.update(evidence.glob("*.dom.html"))
    add_tree(files, evidence / "screenshots")
    runtime = PROJECT / "review" / "H03" / "runtime"
    for name in ("B08_CASES.json", "A07_B08_CONTRACT_RESULTS.json", "B09_CASES.json", "A08_B09_CONTRACT_RESULTS.json"):
        files.add(runtime / name)
    for report in (runtime / "integration-report-A07_B08", runtime / "integration-report-A08_B09"):
        add_tree(files, report)
    missing = [path for path in files if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing package files: {missing}")
    return sorted(files, key=lambda item: item.relative_to(PROJECT).as_posix().casefold())


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 11, 5, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def verify(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        infos = archive.infolist()
        names = [item.filename for item in infos]
        unsafe = [name for name in names if "\\" in name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts]
        symlinks = [item.filename for item in infos if stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF)]
        manifest = json.loads(archive.read(PREFIX + "MANIFEST.json"))
        mismatches = []
        for item in manifest["payloads"]:
            name = PREFIX + item["path"]
            try:
                value = archive.read(name)
            except KeyError:
                mismatches.append({"path": item["path"], "reason": "missing"})
                continue
            if len(value) != item["bytes"] or hashlib.sha256(value).hexdigest() != item["sha256"]:
                mismatches.append({"path": item["path"], "reason": "size_or_sha256"})
        expected = {PREFIX + "MANIFEST.json", *(PREFIX + item["path"] for item in manifest["payloads"])}
        return {
            "entry_count": len(names),
            "payload_count": len(manifest["payloads"]),
            "crc": "PASS" if bad is None else "FAIL",
            "missing_mismatch": len(mismatches),
            "undeclared": len(set(names) - expected),
            "missing_declared": len(expected - set(names)),
            "duplicates": len(names) - len(set(names)),
            "case_collisions": len(names) - len({name.casefold() for name in names}),
            "unsafe_paths": len(unsafe),
            "symlinks": len(symlinks),
        }


def main() -> None:
    if RELEASE.exists() or UPLOAD.exists():
        raise RuntimeError("H03 delivery already exists; immutable package will not be overwritten")
    files = selected_files()
    payloads = []
    for path in files:
        value = path.read_bytes()
        payloads.append({"path": path.relative_to(PROJECT).as_posix(), "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()})
    manifest = {
        "schema_version": "CDH-H03-REVIEW-MANIFEST-1",
        "task_id": "CDH-H03-A07-B08-INTEGRATION-JOURNEY-001",
        "authority": "AUTHORIZED_SYNTHETIC_OFFLINE_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_r05_sha256": "d0993915ff725541ca0c5053f32eddca82888082fcd1b9650f35d80c738237cd",
        "a07_sha256": "390499b3c99b2d3b551530be357f2810d6299db7c8cbd8ab182cf8ca2e19db90",
        "b08_sha256": "a6d5ffb65860fcb33504baefd3c5288c1c75aac0494af248bb3e4c5624cd69bd",
        "a08_sha256": "5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d",
        "b09_sha256": "10f7ae283108b460ce533b52b75ba1698218632b38d5b58fbda8e643b9234bab",
        "status": "READY_FOR_REVIEW_WITH_KNOWN_A08_FIXTURE_DEFECT",
        "known_defects": ["H03-A08-SYNTHETIC-TIMESTAMP-001"],
        "payload_count": len(payloads),
        "payloads": payloads,
    }
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.writestr(zip_info(PREFIX + path.relative_to(PROJECT).as_posix()), path.read_bytes())
        archive.writestr(zip_info(PREFIX + "MANIFEST.json"), json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    shutil.copyfile(RELEASE, UPLOAD)
    release_sha = sha256(RELEASE)
    upload_sha = sha256(UPLOAD)
    integrity = verify(RELEASE)
    with tempfile.TemporaryDirectory(prefix="h03-replay-", dir=PROJECT / "review" / "H03") as temporary:
        target = Path(temporary)
        with zipfile.ZipFile(RELEASE) as archive:
            archive.extractall(target)
        extracted_manifest = json.loads((target / PACKAGE / "MANIFEST.json").read_text(encoding="utf-8"))
        extracted_mismatches = 0
        for item in extracted_manifest["payloads"]:
            path = target / PACKAGE / Path(*PurePosixPath(item["path"]).parts)
            if not path.is_file() or path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
                extracted_mismatches += 1
    all_pass = release_sha == upload_sha and all(value == 0 or key in {"entry_count", "payload_count"} for key, value in integrity.items() if key != "crc") and integrity["crc"] == "PASS" and extracted_mismatches == 0
    result = {
        "task_id": manifest["task_id"],
        "release": str(RELEASE.relative_to(PROJECT)).replace("\\", "/"),
        "upload_copy": str(UPLOAD.relative_to(PROJECT)).replace("\\", "/"),
        "release_sha256": release_sha,
        "upload_sha256": upload_sha,
        "identical_copy": release_sha == upload_sha and RELEASE.read_bytes() == UPLOAD.read_bytes(),
        "manifest_sha256": hashlib.sha256((json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")).hexdigest(),
        "integrity": integrity,
        "extracted_replay_mismatch": extracted_mismatches,
        "status": "PASS" if all_pass else "FAIL",
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if not all_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
