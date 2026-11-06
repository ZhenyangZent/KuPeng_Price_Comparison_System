"""Pinned A11/B11 archive verification for F09 tests."""

from __future__ import annotations

import hashlib
import json
import pathlib
import zipfile
from dataclasses import dataclass
from pathlib import Path


A11_SHA256 = "40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd"
B11_SHA256 = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"


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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_release(path: Path, *, expected_sha256: str, release_root: str, manifest_basename: str) -> ReleaseEvidence:
    if path.is_symlink() or not path.is_file():
        raise ReleaseGateError("RELEASE_FILE_INVALID", str(path))
    digest = _sha(path.read_bytes())
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
        payloads = manifest.get("payloads")
        if not isinstance(payloads, list):
            raise ReleaseGateError("RELEASE_MANIFEST_INVALID", manifest_name)
        declared: dict[str, tuple[int, str]] = {}
        for item in payloads:
            raw_path = item["path"]
            full_path = raw_path if raw_path.startswith(release_root + "/") else f"{release_root}/{raw_path}"
            declared[full_path] = (item.get("bytes", item.get("size")), item["sha256"])
        actual = set(names) - {manifest_name}
        if set(declared) != actual:
            raise ReleaseGateError("RELEASE_MANIFEST_COVERAGE_MISMATCH", path.name)
        for name, expected in declared.items():
            data = archive.read(name)
            if (len(data), _sha(data)) != expected:
                raise ReleaseGateError("RELEASE_PAYLOAD_MISMATCH", name)
        return ReleaseEvidence(digest, len(names), len(declared), _sha(raw_manifest))


def compare_a11_embedded_b11(a11_path: Path, b11_path: Path) -> int:
    """Return the count of byte-identical B11 service members embedded in A11."""
    a_prefix = "CDH_A_R09_001_REVIEW/apps/price-web/frontend/upstream/B11_RELEASE/services/price_coupon_v4/"
    b_prefix = "CDH_B_R07_001_REVIEW/services/price_coupon_v4/"
    with zipfile.ZipFile(a11_path) as a11, zipfile.ZipFile(b11_path) as b11:
        a_members = {name[len(a_prefix):]: name for name in a11.namelist() if name.startswith(a_prefix)}
        b_members = {name[len(b_prefix):]: name for name in b11.namelist() if name.startswith(b_prefix)}
        if set(a_members) != set(b_members):
            raise ReleaseGateError("EMBEDDED_B11_MEMBER_SET_MISMATCH", "A11 embedded B11 service member set differs")
        for relative in sorted(a_members):
            if a11.read(a_members[relative]) != b11.read(b_members[relative]):
                raise ReleaseGateError("EMBEDDED_B11_PAYLOAD_MISMATCH", relative)
        return len(a_members)

