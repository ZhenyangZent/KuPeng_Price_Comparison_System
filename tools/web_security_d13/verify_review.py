from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath


PACKAGE_NAME = "CDH_D_R12_001_REVIEW"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name and "\x00" not in name


def main() -> int:
    path = Path(sys.argv[1])
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if archive.testzip() is not None:
            raise RuntimeError("CRC failure")
        if any(not safe(name) for name in names):
            raise RuntimeError("unsafe member path")
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise RuntimeError("duplicate member path")
        if any(((info.external_attr >> 16) & 0o170000) == 0o120000 for info in infos):
            raise RuntimeError("symlink member")
        manifest_name = f"{PACKAGE_NAME}/REVIEW_MANIFEST.json"
        manifest_data = archive.read(manifest_name)
        manifest = json.loads(manifest_data)
        declared = {item["path"]: item for item in manifest["payloads"]}
        actual = set(names) - {manifest_name}
        if set(declared) != actual:
            raise RuntimeError("manifest path set mismatch")
        for name, item in declared.items():
            data = archive.read(name)
            if len(data) != item["bytes"] or digest(data) != item["sha256"]:
                raise RuntimeError(f"payload mismatch: {name}")
        forbidden = [name for name in names if "/.env" in name.casefold() or "__pycache__" in name.casefold() or name.casefold().endswith((".pyc", ".pyo"))]
        if forbidden:
            raise RuntimeError(f"forbidden members: {forbidden}")
        embedded_name = f"{PACKAGE_NAME}/inputs/CDH_B_R12_001_REVIEW.zip"
        if digest(archive.read(embedded_name)) != "d2149952fe1693381f74ac639a770b393b8703a368df68eea990cd5e231cf23b":
            raise RuntimeError("embedded B16 identity mismatch")
    result = {
        "schema_version": "CDH-D13-REVIEW-VERIFY-1",
        "zip_sha256": digest(path.read_bytes()),
        "manifest_sha256": digest(manifest_data),
        "payload_count": len(declared),
        "missing": 0,
        "mismatch": 0,
        "undeclared": 0,
        "duplicates": 0,
        "unsafe_paths": 0,
        "forbidden": 0,
        "crc": "PASS",
        "embedded_b16_sha256_gate": "PASS",
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
