from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from tools.ci_web_g06.audit import audit_zip, safe_extract, sha256_file
from tools.ci_web_g07.audit import _b11_fixture_gate, audit_controlled_release


B11_SHA256 = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"
ENV_EXAMPLE = """# No secret belongs in the frontend. A06 uses the fixed same-origin path below.
# Vite proxies it only to http://127.0.0.1:8765; no public CORS is enabled.
VITE_CDH_DATA_MODE=LOCAL_API
VITE_CDH_PROXY_PATH=/cdh-local-api
"""


def _files(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {item.filename.replace("\\", "/"): archive.read(item) for item in archive.infolist() if not item.is_dir()}


def _finish(result: dict) -> dict:
    clean = not any(result.get(key) for key in ("unsafe", "duplicates", "symlinks", "encrypted", "sensitive_names", "secret_findings", "missing", "mismatches", "undeclared"))
    result["passed"] = bool(result.get("identity_match") and result.get("crc_gate") and result.get("manifest_path") and result.get("manifest_payload_count") and clean and all(gate.get("passed") for gate in result.get("controlled_gates", [])))
    return result


def _a11_dist_gate(files: dict[str, bytes]) -> dict:
    names = [name for name in files if name.endswith("/dist/A11_DIST_MANIFEST.json")]
    if len(names) != 1: return {"passed": False, "reason": "A11 dist manifest cardinality"}
    name = names[0]; base = name.rsplit("/", 1)[0]
    try: manifest = json.loads(files[name].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError): return {"passed": False, "reason": "A11 dist manifest invalid"}
    failures = []
    for item in manifest.get("files", []):
        target = f"{base}/{item['path']}"
        if target not in files or hashlib.sha256(files[target]).hexdigest() != item["sha256"] or len(files[target]) != item["size"]: failures.append(item.get("path"))
    return {"passed": manifest.get("schema_version") == "CDH-A11-DIST-MANIFEST-1" and len(manifest.get("files", [])) == 3 and not failures, "checked": len(manifest.get("files", [])), "failures": failures}


def audit_release(path: Path, expected_sha256: str, kind: str) -> dict:
    if kind == "B11": return audit_controlled_release(path, expected_sha256, "B11")
    result = audit_zip(path, expected_sha256); files = _files(path); result["controlled_gates"] = []
    if kind != "A11":
        result["controlled_gates"].append({"passed": False, "reason": "unsupported kind"}); return _finish(result)
    fixture = _b11_fixture_gate(files)
    env_names = [name for name in files if name.endswith("/.env.example")]
    env_ok = len(env_names) == 1 and files[env_names[0]].decode("utf-8", errors="replace").replace("\r\n", "\n") == ENV_EXAMPLE
    dependency_names = [name for name in files if name.endswith("/dependencies/CDH_B_R07_001_REVIEW.zip")]
    dependency_ok = len(dependency_names) == 1 and hashlib.sha256(files[dependency_names[0]]).hexdigest() == B11_SHA256
    gates = [fixture, {"passed": env_ok, "reason": "exact inert frontend env example"}, {"passed": dependency_ok, "reason": "embedded exact B11 release"}, _a11_dist_gate(files)]
    result["controlled_gates"].extend(gates)
    approved = set(fixture.get("approved_sensitive_paths", [])) | (set(env_names) if env_ok else set())
    result["sensitive_names"] = [name for name in result.get("sensitive_names", []) if name.replace("\\", "/") not in approved]
    result["approved_declared_sensitive_paths"] = sorted(approved)
    return _finish(result)


__all__ = ["audit_release", "safe_extract", "sha256_file"]
