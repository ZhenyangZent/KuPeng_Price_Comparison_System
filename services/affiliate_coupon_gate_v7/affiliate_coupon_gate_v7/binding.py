"""Exact B11-to-F06 release binding for the offline F07 gate."""

from __future__ import annotations

import hashlib
import inspect
import json
import pathlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


B11_SHA256 = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"
F06_SHA256 = "c2db9aa981cbc935b52944516d5b4259829ffa5af892ac3dc7d28fc6b022ac89"
B11_RELEASE_ROOT = "CDH_B_R07_001_REVIEW"
F06_RELEASE_ROOT = "CDH_F_R07_001_REVIEW"


class BindingError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True, slots=True)
class ArchiveEvidence:
    sha256: str
    entries: int
    payloads: int
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class BindingEvidence:
    b11: ArchiveEvidence
    f06: ArchiveEvidence
    b11_fixture_count: int
    adapter_origin: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file(path: Path, name: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise BindingError(f"{name.upper()}_FILE_INVALID", f"{name} must be a regular file")
    return path.resolve()


def _safe_members(archive: zipfile.ZipFile) -> list[str]:
    names = [item.filename for item in archive.infolist()]
    if len(names) != len(set(names)) or len(names) != len(set(name.casefold() for name in names)):
        raise BindingError("ARCHIVE_DUPLICATE_PATH", "archive contains duplicate or case-colliding paths")
    for item in archive.infolist():
        path = pathlib.PurePosixPath(item.filename)
        if item.filename.startswith(("/", "\\")) or ".." in path.parts or (len(item.filename) > 1 and item.filename[1] == ":"):
            raise BindingError("ARCHIVE_UNSAFE_PATH", item.filename)
        if ((item.external_attr >> 16) & 0o170000) == 0o120000:
            raise BindingError("ARCHIVE_SYMLINK", item.filename)
    bad = archive.testzip()
    if bad is not None:
        raise BindingError("ARCHIVE_CRC_FAILURE", bad)
    return names


def _verify_archive(path: Path, *, expected_sha256: str, release_root: str, manifest_name: str) -> tuple[ArchiveEvidence, dict[str, tuple[int, str]]]:
    path = _regular_file(path, "release")
    actual_sha = _sha256(path)
    if actual_sha != expected_sha256:
        raise BindingError("RELEASE_SHA256_MISMATCH", f"expected {expected_sha256}, got {actual_sha}")
    with zipfile.ZipFile(path) as archive:
        names = _safe_members(archive)
        full_manifest = f"{release_root}/{manifest_name}"
        if full_manifest not in names:
            raise BindingError("MANIFEST_MISSING", full_manifest)
        manifest_bytes = archive.read(full_manifest)
        manifest = json.loads(manifest_bytes)
        payloads = manifest.get("payloads")
        if not isinstance(payloads, list):
            raise BindingError("MANIFEST_STRUCTURE_INVALID", "payload list required")
        declared: dict[str, tuple[int, str]] = {}
        for item in payloads:
            raw_path = item.get("path")
            if not isinstance(raw_path, str):
                raise BindingError("MANIFEST_PATH_INVALID", repr(raw_path))
            full_path = raw_path if raw_path.startswith(release_root + "/") else f"{release_root}/{raw_path}"
            if full_path in declared:
                raise BindingError("MANIFEST_DUPLICATE_PATH", full_path)
            size = item.get("bytes", item.get("size"))
            declared[full_path] = (size, item.get("sha256"))
        actual = set(names) - {full_manifest}
        if set(declared) != actual:
            raise BindingError("MANIFEST_COVERAGE_MISMATCH", f"missing={sorted(set(declared)-actual)} undeclared={sorted(actual-set(declared))}")
        for name, expected in declared.items():
            data = archive.read(name)
            if (len(data), hashlib.sha256(data).hexdigest()) != expected:
                raise BindingError("MANIFEST_PAYLOAD_MISMATCH", name)
        evidence = ArchiveEvidence(actual_sha, len(names), len(declared), hashlib.sha256(manifest_bytes).hexdigest())
        return evidence, declared


def _verify_extracted(
    root: Path, *, release_root: str, declared: dict[str, tuple[int, str]],
    manifest_name: str, manifest_sha256: str,
) -> Path:
    release = (root / release_root).resolve()
    if root.is_symlink() or release.is_symlink() or not release.is_dir():
        raise BindingError("EXTRACTED_ROOT_INVALID", str(release))
    expected_relatives = {name.removeprefix(release_root + "/") for name in declared}
    actual_relatives = {
        path.relative_to(release).as_posix()
        for path in release.rglob("*")
        if path.is_file()
    }
    manifest_path = release / manifest_name
    if manifest_path.is_symlink() or not manifest_path.is_file() or _sha256(manifest_path) != manifest_sha256:
        raise BindingError("EXTRACTED_MANIFEST_MISMATCH", manifest_name)
    actual_relatives.discard(manifest_name)
    if expected_relatives != actual_relatives:
        raise BindingError("EXTRACTED_COVERAGE_MISMATCH", f"missing={sorted(expected_relatives-actual_relatives)} undeclared={sorted(actual_relatives-expected_relatives)}")
    for name, expected in declared.items():
        relative = name.removeprefix(release_root + "/")
        path = release / relative
        if path.is_symlink() or (path.stat().st_size, _sha256(path)) != expected:
            raise BindingError("EXTRACTED_PAYLOAD_MISMATCH", relative)
    return release


def _verify_fixtures(b11_release: Path) -> int:
    fixture_root = b11_release / "services" / "price_coupon_v4" / "fixtures" / "b11_suite"
    manifest = json.loads((fixture_root / "FIXTURE_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "CDH-B11-FIXTURE-SUITE-1" or manifest.get("classification") != "CONTRACT_FIXTURE_TEST_ONLY":
        raise BindingError("FIXTURE_MANIFEST_INVALID", "exact B11 synthetic fixture suite required")
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or [item.get("directory") for item in snapshots] != ["active", "expired-source", "revoked-source", "empty-history"]:
        raise BindingError("FIXTURE_SET_INVALID", "canonical four B11 snapshots required")
    for item in snapshots:
        directory = fixture_root / item["directory"]
        for field, hash_field in (("database", "database_sha256"), ("authority", "authority_sha256")):
            path = directory / item[field]
            if path.is_symlink() or not path.is_file() or _sha256(path) != item[hash_field]:
                raise BindingError("FIXTURE_HASH_MISMATCH", f"{item['directory']}/{item[field]}")
    return len(snapshots)


class ExactB11F06Binding:
    """Calls only the adapter module extracted from the exact F06 release."""

    def __init__(
        self, *, b11_zip: Path, b11_extracted: Path, f06_zip: Path, f06_extracted: Path,
        adapter_module: ModuleType,
    ) -> None:
        b11, b11_declared = _verify_archive(b11_zip, expected_sha256=B11_SHA256, release_root=B11_RELEASE_ROOT, manifest_name="REVIEW_MANIFEST.json")
        f06, f06_declared = _verify_archive(f06_zip, expected_sha256=F06_SHA256, release_root=F06_RELEASE_ROOT, manifest_name="MANIFEST.json")
        b11_release = _verify_extracted(
            b11_extracted.resolve(), release_root=B11_RELEASE_ROOT, declared=b11_declared,
            manifest_name="REVIEW_MANIFEST.json", manifest_sha256=b11.manifest_sha256,
        )
        f06_release = _verify_extracted(
            f06_extracted.resolve(), release_root=F06_RELEASE_ROOT, declared=f06_declared,
            manifest_name="MANIFEST.json", manifest_sha256=f06.manifest_sha256,
        )
        expected_adapter_root = (f06_release / "services" / "affiliate_coupon_gate_v6").resolve()
        adapter_origin = Path(inspect.getfile(adapter_module)).resolve()
        if not adapter_origin.is_relative_to(expected_adapter_root):
            raise BindingError("F06_ADAPTER_ORIGIN_MISMATCH", f"adapter loaded from {adapter_origin}")
        for name in ("adapt_search_envelope", "adapt_detail_envelope", "AffiliateCouponGateV6"):
            if not callable(getattr(adapter_module, name, None)):
                raise BindingError("F06_ADAPTER_API_MISSING", name)
        self.adapter = adapter_module
        self.b11_release = b11_release
        self.f06_release = f06_release
        self.evidence = BindingEvidence(b11, f06, _verify_fixtures(b11_release), str(adapter_origin))

    def adapt_search(self, payload: object):
        return self.adapter.adapt_search_envelope(payload)

    def adapt_detail(self, payload: object):
        return self.adapter.adapt_detail_envelope(payload)

    def evaluate(self, **kwargs: Any):
        return self.adapter.AffiliateCouponGateV6().evaluate(**kwargs)
