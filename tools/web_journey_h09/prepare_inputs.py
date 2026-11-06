from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
H09 = ROOT / "review" / "H09"
BASELINES = H09 / "baselines"
REPORT = H09 / "INPUT_READBACK.json"
SPECS = {
    "A13_REV3": {
        "path": ROOT / "review" / "releases" / "CDH_A_R11_003_REVIEW.zip",
        "sha256": "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274",
        "manifest": "CDH_A_R11_003_REVIEW/SHA256_MANIFEST.json", "prefix": "CDH_A_R11_003_REVIEW/",
    },
    "B15_REV2": {
        "path": ROOT / "review" / "releases" / "CDH_B_R11_002_REVIEW.zip",
        "sha256": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
        "manifest": "CDH_B_R11_002_REVIEW/REVIEW_MANIFEST.json", "prefix": "",
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_member(name: str) -> bool:
    pure = PurePosixPath(name)
    return "\\" not in name and not pure.is_absolute() and ".." not in pure.parts


def verify(label: str, spec: dict[str, object]) -> tuple[dict[str, object], zipfile.ZipFile]:
    source = Path(spec["path"])
    if not source.is_file():
        raise FileNotFoundError(f"{label} missing: {source}")
    actual = sha256_file(source)
    if actual != spec["sha256"]:
        raise RuntimeError(f"{label} SHA mismatch: {actual}")
    archive = zipfile.ZipFile(source)
    infos = archive.infolist(); names = [info.filename for info in infos]
    unsafe = [name for name in names if not safe_member(name)]
    symlinks = [info.filename for info in infos if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)]
    duplicates = len(names) - len(set(names)); case_collisions = len(names) - len({name.casefold() for name in names})
    crc_bad = archive.testzip()
    if crc_bad or unsafe or symlinks or duplicates or case_collisions:
        archive.close()
        raise RuntimeError(f"{label} archive safety failed")
    manifest_bytes = archive.read(str(spec["manifest"])); manifest = json.loads(manifest_bytes)
    mismatches: list[str] = []
    for item in manifest["payloads"]:
        member = str(spec["prefix"]) + item["path"]
        try:
            data = archive.read(member)
        except KeyError:
            mismatches.append(f"missing:{member}"); continue
        size = item.get("bytes", item.get("size"))
        if len(data) != size or sha256_bytes(data) != item["sha256"]:
            mismatches.append(f"mismatch:{member}")
    if mismatches:
        archive.close(); raise RuntimeError(f"{label} manifest mismatch count={len(mismatches)}")
    return {
        "path": source.relative_to(ROOT).as_posix(), "sha256": actual, "bytes": source.stat().st_size,
        "entries": len(names), "manifest_path": spec["manifest"], "manifest_sha256": sha256_bytes(manifest_bytes),
        "manifest_declared": len(manifest["payloads"]), "manifest_mismatch": 0, "crc": "PASS",
        "unsafe_paths": 0, "symlinks": 0, "duplicates": 0, "case_collisions": 0,
        "task_id": manifest.get("task_id"), "schema_version": manifest.get("schema_version"),
    }, archive


def main() -> None:
    BASELINES.mkdir(parents=True, exist_ok=True); inputs = {}
    for label, spec in SPECS.items():
        result, archive = verify(label, spec)
        target = BASELINES / label; target.mkdir(parents=True, exist_ok=True)
        archive.extractall(target); archive.close()
        result["extracted_path"] = target.relative_to(ROOT).as_posix(); inputs[label] = result
    payload = {
        "task_id": "CDH-H09-A13REV3-B15REV2-WINDOWS-E2E-001",
        "status": "PASS_EXACT_INPUTS_AVAILABLE", "inputs": inputs,
    }
    H09.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
