from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath


TEXT_SUFFIXES = {".env", ".ini", ".js", ".json", ".md", ".mjs", ".ps1", ".py", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml"}
SENSITIVE_NAME = re.compile(r"(?i)(^|/)(cookies?($|\.)|id_rsa$|[^/]+\.(pem|p12|pfx|key|sqlite|sqlite3|db)$|\.env($|\.))")
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


def normalize_member(name: str) -> tuple[str | None, str | None]:
    value = name.replace("\\", "/")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return None, "ABSOLUTE_PATH"
    parts = PurePosixPath(value).parts
    if not parts or ".." in parts:
        return None, "PATH_TRAVERSAL"
    return str(PurePosixPath(*parts)), None


def _is_safe_env_example(name: str, data: bytes) -> bool:
    if not name.casefold().endswith(".env.example"):
        return False
    text = data.decode("utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip().strip("'\"")
        safe_public_value = bool(re.fullmatch(r"[A-Z][A-Z0-9_]*|/[A-Za-z0-9_./-]*|https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/.*)?", value))
        if value and not safe_public_value and not any(marker in value.casefold() for marker in PLACEHOLDERS):
            return False
    return True


def secret_findings(name: str, data: bytes) -> list[dict]:
    suffix = Path(name).suffix.casefold()
    lowered_name = name.casefold()
    if suffix not in TEXT_SUFFIXES and not lowered_name.endswith(".env") and not lowered_name.endswith(".env.example"):
        return []
    if len(data) > 2 * 1024 * 1024:
        return []
    text = data.decode("utf-8", errors="replace")
    findings: list[dict] = []
    for rule, pattern in SECRET_RULES.items():
        for match in pattern.finditer(text):
            context = text[max(0, match.start() - 60): min(len(text), match.end() + 60)].casefold()
            if any(marker in context for marker in PLACEHOLDERS):
                continue
            findings.append({"path": name, "rule": rule, "offset": match.start()})
    return findings


def _manifest_entries(manifest: dict) -> list[dict]:
    source = manifest.get("files")
    if source is None:
        source = manifest.get("items")
    if source is None:
        source = manifest.get("payloads")
    if isinstance(source, dict):
        return [{"path": str(path), "sha256": str(value), "bytes": None} for path, value in source.items()]
    if not isinstance(source, list):
        return []
    result = []
    for item in source:
        if not isinstance(item, dict) or "path" not in item or "sha256" not in item:
            continue
        result.append({"path": str(item["path"]), "sha256": str(item["sha256"]), "bytes": item.get("bytes", item.get("size"))})
    return result


def audit_zip(path: Path, expected_sha256: str) -> dict:
    result = {
        "path": str(path.resolve()), "expected_sha256": expected_sha256, "sha256": None,
        "identity_match": False, "entry_count": 0, "crc_gate": False, "manifest_path": None,
        "manifest_payload_count": 0, "unsafe_entries": [], "duplicate_entries": [],
        "symlink_entries": [], "encrypted_entries": [], "sensitive_named_entries": [],
        "secret_findings": [], "manifest_missing": [], "manifest_mismatches": [],
        "manifest_undeclared": [], "checksum_sidecar_gate": None, "passed": False,
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
                name, error = normalize_member(info.filename)
                if error or name is None:
                    result["unsafe_entries"].append({"path": info.filename, "reason": error})
                    continue
                folded = name.casefold()
                if folded in seen:
                    result["duplicate_entries"].append(name)
                seen.add(folded)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    result["symlink_entries"].append(name)
                if info.flag_bits & 1:
                    result["encrypted_entries"].append(name)
                if not info.is_dir():
                    data = archive.read(info)
                    files[name] = data
                    if SENSITIVE_NAME.search(name) and not _is_safe_env_example(name, data):
                        result["sensitive_named_entries"].append(name)
                    result["secret_findings"].extend(secret_findings(name, data))
            result["crc_gate"] = archive.testzip() is None
            candidates = sorted((name for name in files if PurePosixPath(name).name in {"SHA256_MANIFEST.json", "REVIEW_MANIFEST.json", "MANIFEST.json"}), key=lambda x: (len(PurePosixPath(x).parts), x))
            if candidates:
                manifest_name = candidates[0]
                result["manifest_path"] = manifest_name
                manifest = json.loads(files[manifest_name].decode("utf-8"))
                entries = _manifest_entries(manifest)
                result["manifest_payload_count"] = len(entries)
                base = PurePosixPath(manifest_name).parent
                declared: set[str] = set()
                for item in entries:
                    raw = item["path"].replace("\\", "/")
                    full = str(PurePosixPath(raw) if str(base) == "." else base / raw)
                    declared.add(full)
                    data = files.get(full)
                    if data is None:
                        result["manifest_missing"].append(full)
                    else:
                        if item["bytes"] is not None and len(data) != int(item["bytes"]):
                            result["manifest_mismatches"].append({"path": full, "reason": "BYTES"})
                        if sha256_bytes(data) != item["sha256"].casefold():
                            result["manifest_mismatches"].append({"path": full, "reason": "SHA256"})
                result["manifest_undeclared"] = sorted(name for name in files if name != manifest_name and name not in declared)
                sidecar = str(base / "SHA256SUMS.txt") if str(base) != "." else "SHA256SUMS.txt"
                if result["manifest_undeclared"] == [sidecar]:
                    checksum_ok = True
                    checksum_declared: set[str] = set()
                    for raw_line in files[sidecar].decode("utf-8").splitlines():
                        line = raw_line.strip()
                        if not line:
                            continue
                        match = re.fullmatch(r"([0-9a-fA-F]{64})\s{2}(.+)", line)
                        if not match:
                            checksum_ok = False
                            break
                        relative = match.group(2).replace("\\", "/")
                        full = str(base / relative) if str(base) != "." else relative
                        checksum_declared.add(full)
                        if full not in files or sha256_bytes(files[full]) != match.group(1).casefold():
                            checksum_ok = False
                    expected_sidecar_files = declared | {manifest_name}
                    checksum_ok = checksum_ok and checksum_declared == expected_sidecar_files
                    result["checksum_sidecar_gate"] = checksum_ok
                    if checksum_ok:
                        result["manifest_undeclared"] = []
    except (OSError, RuntimeError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        result["error"] = f"ZIP_AUDIT_ERROR: {exc}"
        return result
    result["passed"] = bool(result["identity_match"] and result["crc_gate"] and result["manifest_path"] and result["manifest_payload_count"] and not any(result[key] for key in ("unsafe_entries", "duplicate_entries", "symlink_entries", "encrypted_entries", "sensitive_named_entries", "secret_findings", "manifest_missing", "manifest_mismatches", "manifest_undeclared")))
    return result


def safe_extract(path: Path, destination: Path) -> None:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name, error = normalize_member(info.filename)
            if error or name is None:
                raise ValueError(f"unsafe ZIP member: {info.filename}: {error}")
            target = (destination / Path(*PurePosixPath(name).parts)).resolve()
            if destination not in target.parents and target != destination:
                raise ValueError(f"ZIP member escaped destination: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
