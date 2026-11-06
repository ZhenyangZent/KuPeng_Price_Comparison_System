from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

from tools.ci_web_g06.audit import audit_zip, safe_extract, sha256_file
from tools.ci_web_g07.audit import _b11_fixture_gate, audit_controlled_release


def _files(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {info.filename.replace("\\", "/"): archive.read(info) for info in archive.infolist() if not info.is_dir()}


def _finish(result: dict) -> dict:
    result["passed"] = bool(result.get("identity_match") and result.get("crc_gate") and result.get("manifest_path") and result.get("manifest_payload_count") and not any(result.get(key) for key in ("unsafe", "duplicates", "symlinks", "encrypted", "sensitive_names", "secret_findings", "missing", "mismatches", "undeclared")) and all(gate.get("passed") for gate in result.get("controlled_gates", [])))
    return result


def _env_gate(files: dict[str, bytes], names: list[str]) -> dict:
    allowed = {
        "# Inert documentation only; this module never reads environment files.\nCDH_AFFILIATE_GATE_MODE=disabled\n",
        "# Inert documentation only. This module never loads environment files.\nCDH_AFFILIATE_COUPON_GATE_MODE=disabled\n",
    }
    failures = [name for name in names if files.get(name, b"").decode("utf-8", errors="replace") not in allowed]
    return {"passed": not failures, "approved_sensitive_paths": [] if failures else names, "failures": failures}


def _c09_sidecars(files: dict[str, bytes]) -> dict:
    sum_names = [name for name in files if name.endswith("/SHA256SUMS.txt")]
    info_names = [name for name in files if name.endswith("/RELEASE_INFO.json")]
    if len(sum_names) != 1 or len(info_names) != 1: return {"passed": False, "reason": "sidecar cardinality"}
    base = sum_names[0].rsplit("/", 1)[0]; checked = 0; failures = []
    for line in files[sum_names[0]].decode("utf-8").splitlines():
        digest, relative = line.split("  ", 1); name = f"{base}/{relative.replace('\\', '/')}"; checked += 1
        if name not in files or hashlib.sha256(files[name]).hexdigest() != digest: failures.append(relative)
    try: info = json.loads(files[info_names[0]].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError): info = None
    return {"passed": checked == 28 and not failures and isinstance(info, dict), "checked": checked, "failures": failures, "approved_undeclared": [sum_names[0], info_names[0]]}


def audit_release(path: Path, expected_sha256: str, kind: str) -> dict:
    if kind == "B11": return audit_controlled_release(path, expected_sha256, "B11")
    result = audit_zip(path, expected_sha256); files = _files(path) if path.is_file() else {}
    result["controlled_gates"] = []
    if kind == "A10":
        gate = _b11_fixture_gate(files); approved = set(gate.get("approved_sensitive_paths", [])); result["controlled_gates"].append(gate)
        result["sensitive_names"] = [name for name in result.get("sensitive_names", []) if name.replace("\\", "/") not in approved]
        result["approved_declared_sensitive_paths"] = sorted(approved)
    elif kind == "C09":
        gate = _c09_sidecars(files); result["controlled_gates"].append(gate)
        approved = set(gate.get("approved_undeclared", [])); result["undeclared"] = [name for name in result.get("undeclared", []) if name.replace("\\", "/") not in approved]
        result["approved_undeclared_sidecars"] = sorted(approved)
    elif kind == "F07":
        b11 = _b11_fixture_gate(files); env_names = [name for name in files if name.endswith("/.env.example")]; env = _env_gate(files, env_names)
        approved = set(b11.get("approved_sensitive_paths", [])) | set(env.get("approved_sensitive_paths", [])); result["controlled_gates"].extend((b11, env))
        result["sensitive_names"] = [name for name in result.get("sensitive_names", []) if name.replace("\\", "/") not in approved]
        result["approved_declared_sensitive_paths"] = sorted(approved)
    elif kind == "B12":
        result["controlled_gates"].append({"passed": True, "reason": "no controlled exception needed"})
    else: result["controlled_gates"].append({"passed": False, "reason": "unsupported kind"})
    return _finish(result)


__all__ = ["audit_release", "safe_extract", "sha256_file"]
