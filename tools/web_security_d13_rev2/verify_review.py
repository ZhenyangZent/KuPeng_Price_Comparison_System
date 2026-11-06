from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath


NAME = "CDH_D_R12_002_REVIEW"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe(name: str) -> bool:
    value = PurePosixPath(name)
    return bool(name) and not value.is_absolute() and ".." not in value.parts and "\\" not in name and "\x00" not in name


def main() -> int:
    path = Path(sys.argv[1])
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if archive.testzip() is not None:
            raise RuntimeError("CRC failure")
        if any(not safe(name) for name in names):
            raise RuntimeError("unsafe member")
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise RuntimeError("duplicate member")
        if any(((item.external_attr >> 16) & 0o170000) == 0o120000 for item in infos):
            raise RuntimeError("link member")
        manifest_name = f"{NAME}/REVIEW_MANIFEST.json"
        manifest_data = archive.read(manifest_name)
        manifest = json.loads(manifest_data)
        declared = {item["path"]: item for item in manifest["payloads"]}
        actual = set(names) - {manifest_name}
        if set(declared) != actual:
            raise RuntimeError("manifest path mismatch")
        for name, item in declared.items():
            data = archive.read(name)
            if len(data) != item["bytes"] or digest(data) != item["sha256"]:
                raise RuntimeError(f"payload mismatch: {name}")
        forbidden = [name for name in names if "/.env" in name.casefold() or "__pycache__" in name.casefold() or name.casefold().endswith((".pyc", ".pyo"))]
        if forbidden:
            raise RuntimeError(f"forbidden members: {forbidden}")
        b16_gate = digest(archive.read(f"{NAME}/inputs/CDH_B_R12_002_REVIEW.zip")) == "6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6"
        d13_gate = digest(archive.read(f"{NAME}/inputs/CDH_D_R12_001_REVIEW.zip")) == "eeb7b434db360818399414133cdb9e173654ea6850ea0a76ac702a626f806d2f"
        if not b16_gate or not d13_gate:
            raise RuntimeError("embedded input identity mismatch")
    result = {"schema_version": "CDH-D13-REV2-REVIEW-VERIFY-1", "zip_sha256": digest(path.read_bytes()), "manifest_sha256": digest(manifest_data), "payload_count": len(declared), "missing": 0, "mismatch": 0, "undeclared": 0, "duplicates": 0, "unsafe_paths": 0, "forbidden": 0, "crc": "PASS", "embedded_b16_rev2_gate": "PASS", "embedded_original_d13_gate": "PASS"}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
