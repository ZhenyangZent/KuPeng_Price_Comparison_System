from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
H08 = ROOT / "review" / "H08"
BASELINES = H08 / "baselines"
REPORT = H08 / "INPUT_READBACK.json"
SPECS = {
    "R10": {
        "path": ROOT / "input" / "orchestrator_bundles" / "UNIFIED_CONTINUOUS_20261105_R10" / "CDH_UNIFIED_CONTINUOUS_20261105_R10.zip",
        "sha256": "0474031243db86ffc7c7b05e7569f701f5705cf84a25b98453b987f1c99b7abc",
        "manifest": "MANIFEST.json", "list_key": "payloads", "prefix": "", "extract": False,
    },
    "A11_R09": {
        "path": ROOT / "review" / "releases" / "CDH_A_R09_001_REVIEW.zip",
        "sha256": "40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd",
        "manifest": "CDH_A_R09_001_REVIEW/SHA256_MANIFEST.json", "list_key": "payloads",
        "prefix": "CDH_A_R09_001_REVIEW/", "extract": True,
    },
    "B11_R07": {
        "path": ROOT / "review" / "releases" / "CDH_B_R07_001_REVIEW.zip",
        "sha256": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
        "manifest": "CDH_B_R07_001_REVIEW/REVIEW_MANIFEST.json", "list_key": "payloads",
        "prefix": "", "extract": True,
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
    duplicate_count = len(names) - len(set(names))
    case_collision_count = len(names) - len({name.casefold() for name in names})
    crc_bad = archive.testzip()
    if crc_bad or unsafe or symlinks or duplicate_count or case_collision_count:
        archive.close()
        raise RuntimeError(
            f"{label} archive safety failed: crc_bad={crc_bad!r}, unsafe={len(unsafe)}, "
            f"symlinks={len(symlinks)}, duplicates={duplicate_count}, case_collisions={case_collision_count}"
        )
    manifest_bytes = archive.read(spec["manifest"])
    manifest = json.loads(manifest_bytes)
    items = manifest[spec["list_key"]]
    mismatches: list[str] = []
    declared: set[str] = set()
    for item in items:
        member = spec["prefix"] + item["path"]
        declared.add(member)
        try:
            data = archive.read(member)
        except KeyError:
            mismatches.append(f"missing:{member}")
            continue
        size = item.get("bytes", item.get("size"))
        if len(data) != size or hashlib.sha256(data).hexdigest() != item["sha256"]:
            mismatches.append(f"mismatch:{member}")
    if mismatches:
        archive.close()
        raise RuntimeError(f"{label} manifest mismatches: {mismatches[:5]}")
    return {
        "path": source.relative_to(ROOT).as_posix(), "sha256": actual, "bytes": source.stat().st_size,
        "entries": len(names), "manifest_path": spec["manifest"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "manifest_declared": len(items),
        "manifest_mismatch": 0, "crc": "PASS", "duplicates": 0, "case_collisions": 0,
        "unsafe_paths": 0, "symlinks": 0, "task_id": manifest.get("task_id"),
    }, archive


def main() -> None:
    BASELINES.mkdir(parents=True, exist_ok=True)
    inputs = {}
    for label, spec in SPECS.items():
        result, archive = verify(label, spec)
        if spec["extract"]:
            target = BASELINES / label
            target.mkdir(parents=True, exist_ok=True)
            archive.extractall(target)
            result["extracted_path"] = target.relative_to(ROOT).as_posix()
        archive.close()
        inputs[label] = result
    inputs["A11_R09"]["central_ack_state"] = "RECEIVED_ACK_ONLY_NOT_FUNCTIONAL_PASS"
    payload = {
        "task_id": "CDH-H08-A11-B11-DAILY-DOM-AND-LAUNCHER-JOURNEY-001",
        "status": "PASS_INPUT_INTEGRITY_PINNED_R10",
        "inputs": inputs,
    }
    H08.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
