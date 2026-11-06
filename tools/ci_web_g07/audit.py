from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from tools.ci_web_g06.audit import audit_zip, safe_extract, sha256_bytes, sha256_file


def _find(files: dict[str, bytes], suffix: str) -> tuple[str, bytes]:
    matches = [(name, data) for name, data in files.items() if name.replace("\\", "/").endswith(suffix)]
    if len(matches) != 1: raise ValueError(f"expected one {suffix}, found {len(matches)}")
    return matches[0]


def _b11_fixture_gate(files: dict[str, bytes]) -> dict:
    try:
        manifest_name, raw = _find(files, "services/price_coupon_v4/fixtures/b11_suite/FIXTURE_MANIFEST.json")
        manifest = json.loads(raw.decode("utf-8")); base = str(PurePosixPath(manifest_name).parent)
        if manifest.get("classification") != "CONTRACT_FIXTURE_TEST_ONLY" or manifest.get("schema_version") != "CDH-B11-FIXTURE-SUITE-1":
            raise ValueError("fixture classification/schema invalid")
        approved = []
        for snapshot in manifest.get("snapshots", []):
            directory = snapshot["directory"]
            db_name = f"{base}/{directory}/{snapshot['database']}"; authority_name = f"{base}/{directory}/{snapshot['authority']}"
            db = files[db_name]; authority_raw = files[authority_name]; authority = json.loads(authority_raw.decode("utf-8"))
            if sha256_bytes(db) != snapshot["database_sha256"] or sha256_bytes(authority_raw) != snapshot["authority_sha256"]:
                raise ValueError(f"fixture SHA mismatch: {directory}")
            if authority.get("database_sha256") != snapshot["database_sha256"] or authority.get("data_classification") != "SYNTHETIC_FIXTURE" or authority.get("contains_private_data") is not False:
                raise ValueError(f"fixture authority invalid: {directory}")
            approved.append(db_name)
        return {"passed": len(approved) == 4, "approved_sensitive_paths": approved, "snapshot_count": len(approved), "reason": None}
    except (KeyError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"passed": False, "approved_sensitive_paths": [], "snapshot_count": 0, "reason": str(exc)}


def _f06_env_gate(files: dict[str, bytes]) -> dict:
    try:
        name, raw = _find(files, "services/affiliate_coupon_gate_v6/.env.example")
        text = raw.decode("utf-8")
        passed = text == "# Inert documentation only. This module never loads environment files.\nCDH_AFFILIATE_COUPON_GATE_MODE=disabled\n"
        return {"passed": passed, "approved_sensitive_paths": [name] if passed else [], "reason": None if passed else "unexpected .env.example bytes"}
    except (ValueError, UnicodeDecodeError) as exc:
        return {"passed": False, "approved_sensitive_paths": [], "reason": str(exc)}


def audit_controlled_release(path: Path, expected_sha256: str, kind: str) -> dict:
    result = audit_zip(path, expected_sha256)
    if not path.is_file(): return result
    with zipfile.ZipFile(path) as archive:
        files = {info.filename.replace("\\", "/"): archive.read(info) for info in archive.infolist() if not info.is_dir()}
    exception = _b11_fixture_gate(files) if kind == "B11" else _f06_env_gate(files) if kind == "F06" else {"passed": False, "approved_sensitive_paths": [], "reason": "unsupported release kind"}
    approved = set(exception["approved_sensitive_paths"])
    original = [name.replace("\\", "/") for name in result.get("sensitive_names", [])]
    result["approved_declared_sensitive_paths"] = sorted(name for name in original if name in approved)
    result["sensitive_names"] = sorted(name for name in original if name not in approved)
    result["controlled_exception_gate"] = exception
    result["passed"] = bool(result.get("identity_match") and result.get("crc_gate") and result.get("manifest_path") and result.get("manifest_payload_count") and exception["passed"] and not any(result.get(key) for key in ("unsafe", "duplicates", "symlinks", "encrypted", "sensitive_names", "secret_findings", "missing", "mismatches", "undeclared")))
    return result


__all__ = ["audit_controlled_release", "safe_extract", "sha256_file"]
