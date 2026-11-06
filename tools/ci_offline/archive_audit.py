from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath


TEXT_SUFFIXES = {
    ".csv",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

SENSITIVE_NAME_RE = re.compile(
    r"(?i)(^|/)(\.env($|\.)|cookies?($|\.)|id_rsa$|[^/]+\.(pem|p12|pfx|key|sqlite|sqlite3|db)$)"
)
SECRET_PATTERNS = {
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS_ACCESS_KEY": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GITHUB_TOKEN": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "ASSIGNED_SECRET": re.compile(
        r"(?i)\b(?:api[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*['\"]?([A-Za-z0-9_./+=-]{12,})"
    ),
}
PLACEHOLDER_MARKERS = ("placeholder", "example.invalid", "not-a-secret", "dummy", "fake", "test-only")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_name(name: str) -> tuple[str | None, str | None]:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return None, "ABSOLUTE_PATH"
    parts = PurePosixPath(normalized).parts
    if ".." in parts:
        return None, "PATH_TRAVERSAL"
    cleaned = str(PurePosixPath(*parts))
    return cleaned, None


def _manifest_payloads(manifest: dict) -> list[dict]:
    candidates = manifest.get("payloads")
    if candidates is None:
        candidates = manifest.get("items")
    if candidates is None:
        candidates = manifest.get("files")
    if not isinstance(candidates, list):
        return []
    normalized: list[dict] = []
    for item in candidates:
        if not isinstance(item, dict) or "path" not in item or "sha256" not in item:
            continue
        normalized.append(
            {
                "path": str(item["path"]).replace("\\", "/"),
                "bytes": item.get("bytes", item.get("size")),
                "sha256": str(item["sha256"]).lower(),
            }
        )
    return normalized


def _secret_findings(name: str, data: bytes) -> list[dict]:
    if Path(name).suffix.lower() not in TEXT_SUFFIXES or len(data) > 2 * 1024 * 1024:
        return []
    text = data.decode("utf-8", errors="replace")
    lowered = text.lower()
    findings: list[dict] = []
    for rule, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(text):
            context = text[max(0, match.start() - 40) : min(len(text), match.end() + 40)].lower()
            if any(marker in context for marker in PLACEHOLDER_MARKERS):
                continue
            findings.append({"path": name, "rule": rule, "offset": match.start()})
    return findings


def audit_review_zip(path: Path, expected_sha256: str | None = None) -> dict:
    path = path.resolve()
    result = {
        "path": str(path),
        "exists": path.is_file(),
        "bytes": None,
        "sha256": None,
        "expected_sha256": expected_sha256.lower() if expected_sha256 else None,
        "identity_match": None,
        "entry_count": 0,
        "crc_gate": False,
        "unsafe_entries": [],
        "duplicate_entries": [],
        "symlink_entries": [],
        "encrypted_entries": [],
        "sensitive_named_entries": [],
        "secret_findings": [],
        "manifest_path": None,
        "manifest_payload_count": 0,
        "manifest_missing": [],
        "manifest_mismatches": [],
        "manifest_undeclared": [],
        "passed": False,
    }
    if not path.is_file():
        result["error"] = "ZIP_NOT_FOUND"
        return result
    result["bytes"] = path.stat().st_size
    result["sha256"] = sha256_file(path)
    result["identity_match"] = expected_sha256 is None or result["sha256"] == expected_sha256.lower()
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            result["entry_count"] = len(infos)
            seen: set[str] = set()
            file_data: dict[str, bytes] = {}
            for info in infos:
                normalized, path_error = _normalized_name(info.filename)
                if path_error or normalized is None:
                    result["unsafe_entries"].append({"path": info.filename, "reason": path_error})
                    continue
                folded = normalized.casefold()
                if folded in seen:
                    result["duplicate_entries"].append(normalized)
                seen.add(folded)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    result["symlink_entries"].append(normalized)
                if info.flag_bits & 0x1:
                    result["encrypted_entries"].append(normalized)
                if SENSITIVE_NAME_RE.search(normalized):
                    result["sensitive_named_entries"].append(normalized)
                if not info.is_dir():
                    data = archive.read(info)
                    file_data[normalized] = data
                    result["secret_findings"].extend(_secret_findings(normalized, data))
            result["crc_gate"] = archive.testzip() is None
            manifest_names = sorted(
                (name for name in file_data if name.casefold().endswith("manifest.json")),
                key=lambda value: (len(PurePosixPath(value).parts), value.casefold()),
            )
            if manifest_names:
                manifest_name = manifest_names[0]
                result["manifest_path"] = manifest_name
                manifest = json.loads(file_data[manifest_name].decode("utf-8"))
                payloads = _manifest_payloads(manifest)
                result["manifest_payload_count"] = len(payloads)
                manifest_dir = str(PurePosixPath(manifest_name).parent)
                declared: set[str] = set()
                for payload in payloads:
                    joined = payload["path"] if manifest_dir == "." else f"{manifest_dir}/{payload['path']}"
                    joined = str(PurePosixPath(joined))
                    declared.add(joined)
                    data = file_data.get(joined)
                    if data is None:
                        result["manifest_missing"].append(joined)
                        continue
                    if payload["bytes"] is not None and len(data) != int(payload["bytes"]):
                        result["manifest_mismatches"].append({"path": joined, "reason": "BYTES"})
                    if sha256_bytes(data) != payload["sha256"]:
                        result["manifest_mismatches"].append({"path": joined, "reason": "SHA256"})
                result["manifest_undeclared"] = sorted(
                    name for name in file_data if name != manifest_name and name not in declared
                )
    except (OSError, zipfile.BadZipFile, RuntimeError, json.JSONDecodeError, UnicodeDecodeError) as error:
        result["error"] = f"ZIP_AUDIT_ERROR: {error}"
        return result
    result["passed"] = bool(
        result["identity_match"]
        and result["crc_gate"]
        and result["manifest_path"]
        and result["manifest_payload_count"] > 0
        and not result["unsafe_entries"]
        and not result["duplicate_entries"]
        and not result["symlink_entries"]
        and not result["encrypted_entries"]
        and not result["sensitive_named_entries"]
        and not result["secret_findings"]
        and not result["manifest_missing"]
        and not result["manifest_mismatches"]
        and not result["manifest_undeclared"]
    )
    return result
