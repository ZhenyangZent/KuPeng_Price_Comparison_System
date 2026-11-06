from __future__ import annotations

import hashlib
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "CDH_C01_R04_REVIEW"
STAGE_PARENT = ROOT / "review" / "R04" / "package"
STAGE = STAGE_PARENT / PACKAGE_NAME
RELEASE = ROOT / "review" / "releases" / f"{PACKAGE_NAME}.zip"
VERIFY_PARENT = ROOT / "review" / "R04" / "tmp_zip_verify"
VERIFY_ROOT = VERIFY_PARENT / PACKAGE_NAME
VERIFY_REPORT = ROOT / "review" / "R04" / "zip_verification.txt"

EXCLUDED_DIRS = {".venv", ".git", ".tmp", "__pycache__", ".pytest_cache", ".audit_tmp"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_reset(path: Path, expected_parent: Path, expected_name: str) -> None:
    resolved = path.resolve()
    if resolved.parent != expected_parent.resolve() or resolved.name != expected_name:
        raise RuntimeError(f"unsafe reset target: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.is_dir() or path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        copy_file(path, destination / relative)


def build_stage() -> tuple[int, str]:
    STAGE_PARENT.mkdir(parents=True, exist_ok=True)
    safe_reset(STAGE, STAGE_PARENT, PACKAGE_NAME)
    STAGE.mkdir(parents=True)

    reports = ROOT / "reports" / "R04"
    for name in (
        "README_REVIEW.md",
        "CONTRACT_AND_SCOPE.md",
        "IMPLEMENTATION_SUMMARY.md",
        "FIX_MAPPING.csv",
        "TEST_MAPPING.csv",
        "ZERO_COST_PROVENANCE_AUDIT.md",
        "TEST_RESULTS.md",
        "RISK_REGISTER.md",
        "CHANGE_MANIFEST.csv",
    ):
        copy_file(reports / name, STAGE / name)
    copy_tree(reports, STAGE / "reports" / "R04")
    copy_file(ROOT / "review" / "R04" / "REWORK_PLAN.md", STAGE / "REWORK_PLAN.md")

    copy_file(ROOT / "README.md", STAGE / "source" / "README.md")
    copy_file(ROOT / "pyproject.toml", STAGE / "source" / "pyproject.toml")
    copy_tree(ROOT / "src", STAGE / "source" / "src")
    copy_tree(ROOT / "scripts", STAGE / "source" / "scripts")
    copy_tree(ROOT / "docs", STAGE / "source" / "docs")
    copy_tree(ROOT / "tests", STAGE / "tests")
    copy_tree(ROOT / "tests" / "fixtures", STAGE / "fixtures")
    copy_tree(ROOT / "review" / "R04" / "logs", STAGE / "logs")
    copy_tree(ROOT / "review" / "R04" / "before_after", STAGE / "before_after")
    copy_tree(ROOT / "review" / "R04" / "evidence", STAGE / "evidence")

    audit_root = ROOT / "input" / "orchestrator_audits" / "R03"
    copy_file(
        audit_root / "CDH_C01_R03_ORCHESTRATOR_AUDIT_004.zip",
        STAGE / "evidence" / "controlled_input" / "CDH_C01_R03_ORCHESTRATOR_AUDIT_004.zip",
    )
    copy_tree(
        audit_root / "extracted" / "CDH_C01_R03_ORCHESTRATOR_AUDIT_004",
        STAGE / "evidence" / "controlled_input" / "extracted",
    )

    payloads = sorted(path for path in STAGE.rglob("*") if path.is_file())
    manifest_lines = [f"{sha256(path)}  {path.relative_to(STAGE).as_posix()}" for path in payloads]
    manifest = STAGE / "SHA256SUMS.txt"
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8", newline="\n")
    return len(payloads), sha256(manifest)


def build_zip() -> None:
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    if RELEASE.exists():
        raise FileExistsError(f"refusing to overwrite existing R04 release: {RELEASE}")
    with zipfile.ZipFile(RELEASE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in STAGE.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(STAGE_PARENT).as_posix())


def verify_zip(expected_payload_count: int, expected_manifest_hash: str) -> dict[str, object]:
    exact_names: set[str] = set()
    folded_names: set[str] = set()
    unsafe: list[str] = []
    duplicates: list[str] = []
    symlinks: list[str] = []
    with zipfile.ZipFile(RELEASE) as archive:
        for info in archive.infolist():
            name = info.filename
            pure = PurePosixPath(name)
            if (
                pure.is_absolute()
                or not pure.parts
                or pure.parts[0] != PACKAGE_NAME
                or any(part in ("", ".", "..") for part in pure.parts)
                or ":" in pure.parts[0]
                or "\\" in name
            ):
                unsafe.append(name)
            folded = name.casefold()
            if name in exact_names or folded in folded_names:
                duplicates.append(name)
            exact_names.add(name)
            folded_names.add(folded)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                symlinks.append(name)
        crc_failure = archive.testzip()
        if unsafe or duplicates or symlinks or crc_failure is not None:
            raise RuntimeError(
                f"zip safety failed: unsafe={unsafe}, duplicates={duplicates}, symlinks={symlinks}, crc={crc_failure}"
            )
        VERIFY_PARENT.mkdir(parents=True, exist_ok=True)
        safe_reset(VERIFY_ROOT, VERIFY_PARENT, PACKAGE_NAME)
        archive.extractall(VERIFY_PARENT)

    manifest = VERIFY_ROOT / "SHA256SUMS.txt"
    manifest_hash = sha256(manifest)
    declared: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        if relative in declared:
            raise RuntimeError(f"duplicate manifest path: {relative}")
        declared[relative] = digest
    actual = {
        path.relative_to(VERIFY_ROOT).as_posix(): sha256(path)
        for path in VERIFY_ROOT.rglob("*")
        if path.is_file() and path != manifest
    }
    missing = sorted(set(declared) - set(actual))
    undeclared = sorted(set(actual) - set(declared))
    mismatched = sorted(path for path in declared.keys() & actual.keys() if declared[path] != actual[path])
    if (
        manifest_hash != expected_manifest_hash
        or len(actual) != expected_payload_count
        or missing
        or undeclared
        or mismatched
    ):
        raise RuntimeError(
            "manifest verification failed: "
            f"manifest_hash={manifest_hash}, payloads={len(actual)}, missing={missing}, "
            f"undeclared={undeclared}, mismatched={mismatched}"
        )
    return {
        "zip_sha256": sha256(RELEASE),
        "zip_bytes": RELEASE.stat().st_size,
        "manifest_sha256": manifest_hash,
        "entry_count": len(exact_names),
        "payload_count": len(actual),
        "unsafe": len(unsafe),
        "duplicates": len(duplicates),
        "symlinks": len(symlinks),
        "missing": len(missing),
        "undeclared": len(undeclared),
        "mismatched": len(mismatched),
        "crc": "PASS",
    }


def main() -> None:
    payload_count, manifest_hash = build_stage()
    build_zip()
    result = verify_zip(payload_count, manifest_hash)
    lines = [
        f"PACKAGE={PACKAGE_NAME}",
        f"ZIP={RELEASE}",
        f"ZIP_BYTES={result['zip_bytes']}",
        f"ZIP_SHA256={result['zip_sha256']}",
        f"MANIFEST_SHA256={result['manifest_sha256']}",
        f"ENTRY_COUNT={result['entry_count']}",
        f"PAYLOAD_COUNT={result['payload_count']}",
        f"UNSAFE_PATHS={result['unsafe']}",
        f"DUPLICATES={result['duplicates']}",
        f"SYMLINKS={result['symlinks']}",
        f"MISSING={result['missing']}",
        f"UNDECLARED={result['undeclared']}",
        f"MISMATCHED={result['mismatched']}",
        f"CRC={result['crc']}",
        "STATUS=PASS",
    ]
    VERIFY_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
