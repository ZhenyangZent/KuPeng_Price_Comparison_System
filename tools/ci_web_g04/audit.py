from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath


TEXT_SUFFIXES = {".ini", ".js", ".json", ".md", ".mjs", ".ps1", ".py", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml"}
SENSITIVE_NAME = re.compile(r"(?i)(^|/)(\.env($|\.)|cookies?($|\.)|id_rsa$|[^/]+\.(pem|p12|pfx|key|sqlite|sqlite3|db)$)")
SECRET_RULES = {
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS_ACCESS_KEY": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GITHUB_TOKEN": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "ASSIGNED_SECRET": re.compile(r"(?i)\b(?:api[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|password)\b\s*[:=]\s*['\"]?([A-Za-z0-9_./+=-]{12,})"),
}
PLACEHOLDERS = ("placeholder", "example.invalid", "not-a-secret", "dummy", "fake", "test-only", "changeme")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(name: str) -> tuple[str | None, str | None]:
    value = name.replace("\\", "/")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return None, "ABSOLUTE_PATH"
    parts = PurePosixPath(value).parts
    if not parts or ".." in parts:
        return None, "PATH_TRAVERSAL"
    return str(PurePosixPath(*parts)), None


def _secret_findings(name: str, data: bytes) -> list[dict]:
    lowered = name.casefold()
    if Path(name).suffix.casefold() not in TEXT_SUFFIXES and not lowered.endswith(".env") and not lowered.endswith(".env.example"):
        return []
    if len(data) > 2 * 1024 * 1024:
        return []
    text = data.decode("utf-8", errors="replace")
    findings = []
    for rule, pattern in SECRET_RULES.items():
        for match in pattern.finditer(text):
            context = text[max(0, match.start() - 60):min(len(text), match.end() + 60)].casefold()
            if any(marker in context for marker in PLACEHOLDERS):
                continue
            findings.append({"path": name, "rule": rule, "offset": match.start()})
    return findings


def _safe_env_example(name: str, data: bytes) -> bool:
    return name.casefold().endswith(".env.example") and not _secret_findings(name, data)


def _manifest_entries(value: dict) -> list[dict]:
    source = value.get("files", value.get("items", value.get("payloads")))
    if isinstance(source, dict):
        return [{"path": str(path), "sha256": str(digest), "bytes": None} for path, digest in source.items()]
    if not isinstance(source, list):
        return []
    return [
        {"path": str(item["path"]), "sha256": str(item["sha256"]), "bytes": item.get("bytes", item.get("size"))}
        for item in source if isinstance(item, dict) and "path" in item and "sha256" in item
    ]


def audit_zip(path: Path, expected_sha256: str, *, allowed_undeclared_metadata: tuple[str, ...] = ()) -> dict:
    result = {
        "path": str(path.resolve()), "expected_sha256": expected_sha256.casefold(), "sha256": None,
        "identity_match": False, "entry_count": 0, "file_count": 0, "crc_gate": False,
        "manifest_path": None, "manifest_payload_count": 0, "unsafe": [], "duplicates": [],
        "symlinks": [], "encrypted": [], "sensitive_names": [], "secret_findings": [], "missing": [], "mismatches": [], "undeclared": [],
        "allowed_undeclared_metadata": [], "passed": False,
    }
    if not path.is_file():
        result["error"] = "ZIP_NOT_FOUND"
        return result
    result["sha256"] = sha256_file(path)
    result["identity_match"] = result["sha256"] == expected_sha256.casefold()
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            result["entry_count"] = len(infos)
            files: dict[str, bytes] = {}
            seen: set[str] = set()
            for info in infos:
                name, error = normalize(info.filename)
                if error or name is None:
                    result["unsafe"].append({"path": info.filename, "reason": error})
                    continue
                folded = name.casefold()
                if folded in seen:
                    result["duplicates"].append(name)
                seen.add(folded)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode): result["symlinks"].append(name)
                if info.flag_bits & 1: result["encrypted"].append(name)
                if not info.is_dir():
                    data = archive.read(info); files[name] = data
                    if SENSITIVE_NAME.search(name) and not _safe_env_example(name, data): result["sensitive_names"].append(name)
                    result["secret_findings"].extend(_secret_findings(name, data))
            result["file_count"] = len(files)
            result["crc_gate"] = archive.testzip() is None
            candidates = sorted((name for name in files if PurePosixPath(name).name in {"MANIFEST.json", "REVIEW_MANIFEST.json", "SHA256_MANIFEST.json"}), key=lambda name: (len(PurePosixPath(name).parts), name))
            if candidates:
                manifest_name = candidates[0]
                result["manifest_path"] = manifest_name
                manifest = json.loads(files[manifest_name].decode("utf-8"))
                entries = _manifest_entries(manifest)
                result["manifest_payload_count"] = len(entries)
                base = PurePosixPath(manifest_name).parent
                declared: set[str] = set()
                for entry in entries:
                    raw = entry["path"].replace("\\", "/")
                    direct = str(PurePosixPath(raw))
                    relative = str(PurePosixPath(raw) if str(base) == "." else base / raw)
                    full = direct if direct in files else relative
                    declared.add(full)
                    data = files.get(full)
                    if data is None:
                        result["missing"].append(full)
                        continue
                    if entry["bytes"] is not None and len(data) != int(entry["bytes"]):
                        result["mismatches"].append({"path": full, "reason": "BYTES"})
                    if sha256_bytes(data) != entry["sha256"].casefold():
                        result["mismatches"].append({"path": full, "reason": "SHA256"})
                undeclared = sorted(name for name in files if name != manifest_name and name not in declared)
                allowed = set(allowed_undeclared_metadata)
                result["allowed_undeclared_metadata"] = [name for name in undeclared if name in allowed]
                result["undeclared"] = [name for name in undeclared if name not in allowed]
    except (OSError, RuntimeError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        result["error"] = f"ZIP_AUDIT_ERROR: {exc}"
        return result
    result["passed"] = bool(result["identity_match"] and result["crc_gate"] and result["manifest_path"] and result["manifest_payload_count"] and not any(result[key] for key in ("unsafe", "duplicates", "symlinks", "encrypted", "sensitive_names", "secret_findings", "missing", "mismatches", "undeclared")))
    return result


def safe_extract(path: Path, destination: Path) -> None:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name, error = normalize(info.filename)
            if error or name is None:
                raise ValueError(f"unsafe ZIP member {info.filename}: {error}")
            target = (destination / Path(*PurePosixPath(name).parts)).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError(f"ZIP member escaped destination: {info.filename}")
            if info.is_dir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
