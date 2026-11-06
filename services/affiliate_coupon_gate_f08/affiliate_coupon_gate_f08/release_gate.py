"""Pinned read-only release identity checks used by F08 tests and evidence."""

from __future__ import annotations

import hashlib
import json
import pathlib
import zipfile
from dataclasses import dataclass
from pathlib import Path


B11_SHA256 = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"
F07_SHA256 = "705b8cf34a5315e661de443f27346efa3b97670e81f334f59cb6ab9cd2fff2ee"


class ReleaseGateError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReleaseEvidence:
    sha256: str
    entries: int
    manifest_payloads: int
    manifest_sha256: str


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_release(path: Path, *, expected_sha256: str, release_root: str, manifest_basename: str) -> ReleaseEvidence:
    if path.is_symlink() or not path.is_file():
        raise ReleaseGateError("RELEASE_FILE_INVALID", str(path))
    digest = _sha(path)
    if digest != expected_sha256:
        raise ReleaseGateError("RELEASE_SHA256_MISMATCH", f"expected {expected_sha256}, got {digest}")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if archive.testzip() is not None:
            raise ReleaseGateError("RELEASE_CRC_FAILURE", path.name)
        if len(names) != len(set(names)) or len(names) != len(set(name.casefold() for name in names)):
            raise ReleaseGateError("RELEASE_DUPLICATE_PATH", path.name)
        for item in infos:
            pure = pathlib.PurePosixPath(item.filename)
            if item.filename.startswith(("/", "\\")) or ".." in pure.parts or (len(item.filename) > 1 and item.filename[1] == ":"):
                raise ReleaseGateError("RELEASE_UNSAFE_PATH", item.filename)
            if ((item.external_attr >> 16) & 0o170000) == 0o120000:
                raise ReleaseGateError("RELEASE_SYMLINK", item.filename)
        manifest_name = f"{release_root}/{manifest_basename}"
        raw_manifest = archive.read(manifest_name)
        manifest = json.loads(raw_manifest)
        items = manifest.get("payloads")
        if not isinstance(items, list):
            raise ReleaseGateError("RELEASE_MANIFEST_INVALID", manifest_name)
        declared = {}
        for item in items:
            raw_path = item["path"]
            full_path = raw_path if raw_path.startswith(release_root + "/") else f"{release_root}/{raw_path}"
            declared[full_path] = (item.get("bytes", item.get("size")), item["sha256"])
        actual = set(names) - {manifest_name}
        if set(declared) != actual:
            raise ReleaseGateError("RELEASE_MANIFEST_COVERAGE_MISMATCH", path.name)
        for name, expected in declared.items():
            data = archive.read(name)
            if (len(data), hashlib.sha256(data).hexdigest()) != expected:
                raise ReleaseGateError("RELEASE_PAYLOAD_MISMATCH", name)
        return ReleaseEvidence(digest, len(names), len(declared), hashlib.sha256(raw_manifest).hexdigest())
