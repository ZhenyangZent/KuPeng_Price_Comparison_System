from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "review" / "H10_REV3" / "INPUT_READBACK.json"
SPECS = {
    "A14": {
        "path": ROOT / "review" / "releases" / "CDH_A_R11_004_REVIEW.zip",
        "sha256": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
        "manifest": "CDH_A_R11_004_REVIEW/SHA256_MANIFEST.json",
        "prefix": "CDH_A_R11_004_REVIEW/",
    },
    "B15_REV2": {
        "path": ROOT / "review" / "releases" / "CDH_B_R11_002_REVIEW.zip",
        "sha256": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
        "manifest": "CDH_B_R11_002_REVIEW/REVIEW_MANIFEST.json",
        "prefix": "",
    },
    "G10": {
        "path": ROOT / "review" / "releases" / "CDH_G10_H10_LOOPBACK_DIAGNOSTIC_STATUS_ONLY.zip",
        "sha256": "9efa1ba175e6579a210af092c3e35c7b44c1e60cb69d400fd0b4b3c2bfd91b14",
        "manifest": "CDH_G10_H10_LOOPBACK_DIAGNOSTIC_STATUS_ONLY/MANIFEST.json",
        "prefix": "CDH_G10_H10_LOOPBACK_DIAGNOSTIC_STATUS_ONLY/",
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


def safe(name: str) -> bool:
    value = PurePosixPath(name)
    return "\\" not in name and not value.is_absolute() and ".." not in value.parts


def verify(label: str, spec: dict[str, object]) -> dict[str, object]:
    source = Path(spec["path"])
    actual = sha256_file(source)
    if actual != spec["sha256"]:
        raise RuntimeError(f"{label} SHA mismatch: {actual}")
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if archive.testzip() is not None:
            raise RuntimeError(f"{label} CRC failure")
        if any(not safe(name) for name in names):
            raise RuntimeError(f"{label} unsafe path")
        if any(stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF) for item in infos):
            raise RuntimeError(f"{label} symlink")
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise RuntimeError(f"{label} duplicate or case collision")
        manifest_bytes = archive.read(str(spec["manifest"]))
        manifest = json.loads(manifest_bytes)
        declared = []
        mismatches = []
        for item in manifest["payloads"]:
            member = str(spec["prefix"]) + item["path"]
            declared.append(member)
            data = archive.read(member)
            size = item.get("bytes", item.get("size"))
            if len(data) != size or sha256_bytes(data) != item["sha256"]:
                mismatches.append(member)
        payload_members = [name for name in names if not name.endswith("/") and name != spec["manifest"]]
        undeclared = set(payload_members) - set(declared)
        missing = set(declared) - set(payload_members)
        if mismatches or undeclared or missing or len(declared) != len(set(declared)):
            raise RuntimeError(f"{label} manifest mismatch")
        return {
            "path": source.relative_to(ROOT).as_posix(), "sha256": actual, "bytes": source.stat().st_size,
            "entries": len(names), "manifest_path": spec["manifest"], "manifest_sha256": sha256_bytes(manifest_bytes),
            "manifest_declared": len(declared), "crc": "PASS", "mismatch": 0, "missing": 0, "undeclared": 0,
            "duplicates": 0, "case_collisions": 0, "unsafe_paths": 0, "symlinks": 0,
            "task_id": manifest.get("task_id"), "delivery_type": manifest.get("delivery_type"), "status": manifest.get("status"),
        }


def main() -> None:
    inputs = {label: verify(label, spec) for label, spec in SPECS.items()}
    payload = {"task_id": "CDH-H10-PRIVATE-HISTORY-REOPEN-E2E-001", "revision": "REV3", "status": "PASS", "inputs": inputs}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
