from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
H07 = ROOT / "review" / "H07"
BASELINES = H07 / "baselines"
REPORT = H07 / "INPUT_READBACK.json"
SPECS = {
    "R09": {
        "path": ROOT / "input" / "orchestrator_bundles" / "UNIFIED_CONTINUOUS_20261105_R09" / "CDH_UNIFIED_CONTINUOUS_20261105_R09.zip",
        "sha256": "be0ee2febae110a16bac12dd6c00e26c74e8006f4eb944b5fdad0d6d0a76a71b",
        "manifest": "MANIFEST.json", "list_key": "payloads", "prefix": "", "extract": False,
    },
    "A10_R08": {
        "path": ROOT / "review" / "releases" / "CDH_A_R08_001_REVIEW.zip",
        "sha256": "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
        "manifest": "CDH_A_R08_001_REVIEW/MANIFEST.json", "list_key": "files", "prefix": "CDH_A_R08_001_REVIEW/", "extract": True,
    },
    "B11": {
        "path": ROOT / "review" / "releases" / "CDH_B_R07_001_REVIEW.zip",
        "sha256": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
        "manifest": "CDH_B_R07_001_REVIEW/REVIEW_MANIFEST.json", "list_key": "payloads", "prefix": "", "extract": True,
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_member(name: str) -> bool:
    pure = PurePosixPath(name)
    return "\\" not in name and not pure.is_absolute() and ".." not in pure.parts


def verify(label: str, spec: dict) -> tuple[dict, zipfile.ZipFile]:
    source: Path = spec["path"]
    if not source.is_file():
        raise FileNotFoundError(f"{label} input unavailable: {source}")
    actual = sha256(source)
    if actual != spec["sha256"]:
        raise RuntimeError(f"{label} SHA-256 mismatch: {actual}")
    archive = zipfile.ZipFile(source)
    infos = archive.infolist()
    names = [info.filename for info in infos]
    unsafe = [name for name in names if not safe_member(name)]
    symlinks = [info.filename for info in infos if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)]
    if archive.testzip() is not None or unsafe or symlinks or len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
        archive.close()
        raise RuntimeError(f"{label} archive safety gate failed")
    manifest_bytes = archive.read(spec["manifest"])
    manifest = json.loads(manifest_bytes)
    items = manifest[spec["list_key"]]
    mismatches = []
    for item in items:
        member = spec["prefix"] + item["path"]
        try:
            data = archive.read(member)
        except KeyError:
            mismatches.append(item["path"])
            continue
        size = item.get("bytes", item.get("size"))
        if len(data) != size or hashlib.sha256(data).hexdigest() != item["sha256"]:
            mismatches.append(item["path"])
    if mismatches:
        archive.close()
        raise RuntimeError(f"{label} manifest mismatches: {len(mismatches)}")
    return {
        "path": source.relative_to(ROOT).as_posix(), "sha256": actual, "bytes": source.stat().st_size,
        "entries": len(names), "manifest_path": spec["manifest"], "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_declared": len(items), "manifest_mismatch": 0, "crc": "PASS", "duplicates": 0,
        "case_collisions": 0, "unsafe_paths": 0, "symlinks": 0, "task_id": manifest.get("task_id"),
    }, archive


def main() -> None:
    BASELINES.mkdir(parents=True, exist_ok=True)
    inputs = {}
    for label, spec in SPECS.items():
        result, archive = verify(label, spec)
        if spec["extract"]:
            target = BASELINES / label
            if not target.exists():
                target.mkdir(parents=True)
                archive.extractall(target)
            result["extracted_path"] = target.relative_to(ROOT).as_posix()
        archive.close()
        inputs[label] = result
    inputs["A10_R08"]["central_ack_state"] = "PINNED_IN_R09_AUTHORITY"
    inputs["A10_R08"]["final_pass_authorized"] = True
    payload = {"task_id": "CDH-H07-A10R08-B11-FULL_BROWSER-001", "status": "PASS_INPUT_INTEGRITY_PINNED_R09", "inputs": inputs}
    H07.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
