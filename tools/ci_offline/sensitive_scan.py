from __future__ import annotations

from pathlib import Path

from .archive_audit import SENSITIVE_NAME_RE, TEXT_SUFFIXES, _secret_findings


ALLOWED_PREFIXES = (
    Path("tools/ci_offline"),
    Path("tests/ci_offline"),
    Path("docs/CI_PREVIEW"),
    Path("reports/G02"),
    Path("review/G02"),
)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def scan_allowed_sources(project_root: Path, requested_paths: list[Path]) -> dict:
    project_root = project_root.resolve()
    allowed_roots = [(project_root / value).resolve() for value in ALLOWED_PREFIXES]
    findings: list[dict] = []
    scanned_files = 0
    rejected_paths: list[str] = []
    for requested in requested_paths:
        candidate = requested if requested.is_absolute() else project_root / requested
        candidate = candidate.resolve()
        if not any(_is_relative_to(candidate, allowed) or candidate == allowed for allowed in allowed_roots):
            rejected_paths.append(str(candidate))
            continue
        paths = [candidate] if candidate.is_file() else sorted(candidate.rglob("*")) if candidate.is_dir() else []
        for path in paths:
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(project_root).as_posix()
            scanned_files += 1
            if SENSITIVE_NAME_RE.search(relative):
                findings.append({"path": relative, "rule": "SENSITIVE_NAME"})
            if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 2 * 1024 * 1024:
                findings.extend(_secret_findings(relative, path.read_bytes()))
    return {
        "requested_paths": [str(value) for value in requested_paths],
        "scanned_file_count": scanned_files,
        "rejected_paths": rejected_paths,
        "findings": findings,
        "passed": not findings and not rejected_paths,
    }
