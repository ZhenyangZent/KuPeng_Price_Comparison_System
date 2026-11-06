from __future__ import annotations

import csv
import hashlib
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "CDH_C01_R01_REVIEW"
STAGE_PARENT = ROOT / "review" / "R01" / "package"
STAGE = STAGE_PARENT / PACKAGE_NAME
ZIP_PATH = ROOT / "review" / "releases" / f"{PACKAGE_NAME}.zip"
VERIFY_REPORT = ROOT / "review" / "R01" / "zip_verification.txt"
VERIFY_TEMP = ROOT / "review" / "R01" / "tmp_zip_verify"
ORIGINAL_ZIP = ROOT / "review" / "releases" / "CDH_C01_001_REVIEW.zip"
ORIGINAL_SHA256 = "d40cc857c0a7ccb082ddfcdfa9f2dac1d6856f9b06e66bf7a24a0869e555f0fb"

IGNORED_NAMES = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".tmp"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def allowed(path: Path) -> bool:
    return not any(part in IGNORED_NAMES for part in path.parts) and path.suffix.lower() not in IGNORED_SUFFIXES


def copy_tree(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not allowed(relative):
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def write_change_manifest() -> None:
    changes = [
        ("MODIFIED", "README.md", "R01 execution and fail-closed contract"),
        ("MODIFIED", "pyproject.toml", "core version 0.2.0"),
        ("MODIFIED", "src/cdh_core/models.py", "canonical identities and bound evidence/results"),
        ("MODIFIED", "src/cdh_core/pricing.py", "component/coupon/quote validation"),
        ("MODIFIED", "src/cdh_core/history.py", "exact scenario-bound history"),
        ("MODIFIED", "src/cdh_core/policy.py", "default-deny time/scope-bound policy"),
        ("MODIFIED", "src/cdh_core/persistence.py", "schema 2 canonical replay and two-phase outbox"),
        ("MODIFIED", "src/cdh_core/demo.py", "explicit verified offline context"),
        ("MODIFIED", "tests/test_models_pricing.py", "adapted explicit quote/coupon contract"),
        ("MODIFIED", "tests/test_history_policy.py", "adapted explicit scope/baseline contract"),
        ("MODIFIED", "tests/test_persistence_demo.py", "adapted bound decision/current-state contract"),
        ("ADDED", "tests/test_rework_regressions.py", "17 audit regressions plus hardening/properties"),
        ("MODIFIED", "scripts/generate_traceability.py", "honest R01 evidence mapping"),
        ("ADDED", "scripts/run_r01_validation.ps1", "repeatable R01 validation"),
        ("ADDED", "scripts/package_r01_review.py", "reproducible review package and integrity checks"),
        ("MODIFIED", "docs/architecture/C01_DESIGN.md", "schema 2 claim/finalize architecture"),
        ("ADDED", "docs/architecture/C01_R01_IDENTITY_OUTBOX.md", "identity/migration/outbox contract"),
        ("ADDED", "review/R01/REWORK_PLAN.md", "pre-change P0/P1 work plan"),
        ("ADDED", "reports/R01/*", "R01 review reports and mapping"),
        ("ADDED", "review/R01/before_after/*", "before/after audit evidence"),
        ("ADDED", "review/R01/logs/*", "raw validation logs"),
        ("ADDED", "review/R01/evidence/*", "input/demo/integrity evidence"),
    ]
    output = STAGE / "CHANGE_MANIFEST.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("CHANGE_TYPE", "PROJECT_PATH", "SHA256_OR_SCOPE", "DESCRIPTION"))
        for change_type, relative, description in changes:
            concrete = ROOT / relative
            digest = sha256(concrete) if concrete.is_file() else "MULTIPLE_OR_DIRECTORY"
            writer.writerow((change_type, relative, digest, description))


def build_stage() -> None:
    expected_parent = (ROOT / "review" / "R01" / "package").resolve()
    if STAGE_PARENT.resolve() != expected_parent or STAGE.resolve().parent != expected_parent:
        raise RuntimeError("unsafe stage path")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    report_dir = ROOT / "reports" / "R01"
    for name in (
        "README_REVIEW.md",
        "CONTRACT_AND_SCOPE.md",
        "FIX_MAPPING.csv",
        "IMPLEMENTATION_SUMMARY.md",
        "TEST_RESULTS.md",
        "RISK_REGISTER.md",
    ):
        copy_file(report_dir / name, STAGE / name)
    copy_file(ROOT / "review" / "R01" / "REWORK_PLAN.md", STAGE / "REWORK_PLAN.md")
    copy_file(ROOT / "reports" / "REQUIREMENT_TRACEABILITY.csv", STAGE / "REQUIREMENT_TRACEABILITY.csv")

    copy_file(ROOT / "README.md", STAGE / "source" / "README.md")
    copy_file(ROOT / "pyproject.toml", STAGE / "source" / "pyproject.toml")
    copy_tree(ROOT / "src", STAGE / "source" / "src")
    copy_tree(ROOT / "docs", STAGE / "source" / "docs")
    copy_tree(ROOT / "scripts", STAGE / "source" / "scripts")
    copy_tree(ROOT / "tests", STAGE / "tests")
    copy_tree(ROOT / "review" / "R01" / "logs", STAGE / "logs")
    copy_tree(ROOT / "review" / "R01" / "before_after", STAGE / "before_after")
    copy_tree(ROOT / "review" / "R01" / "evidence", STAGE / "evidence")
    copy_tree(
        ROOT / "input" / "orchestrator_audit" / "extracted" / "CDH_C01_ORCHESTRATOR_AUDIT_001",
        STAGE / "evidence" / "orchestrator_audit",
    )
    write_change_manifest()

    top_manifest = STAGE / "SHA256SUMS.txt"
    payloads = sorted(path for path in STAGE.rglob("*") if path.is_file() and path != top_manifest)
    manifest_lines = [f"{sha256(path)}  {path.relative_to(STAGE).as_posix()}" for path in payloads]
    (STAGE / "SHA256SUMS.txt").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")


def build_zip() -> None:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, (Path(PACKAGE_NAME) / path.relative_to(STAGE)).as_posix())


def verify_zip() -> dict[str, object]:
    with zipfile.ZipFile(ZIP_PATH) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if not names or {PurePosixPath(name).parts[0] for name in names} != {PACKAGE_NAME}:
            raise RuntimeError("archive must contain exactly one expected top-level folder")
        if len(names) != len(set(names)):
            raise RuntimeError("duplicate ZIP entries")
        for info in infos:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise RuntimeError(f"unsafe ZIP path: {info.filename}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise RuntimeError(f"symlink prohibited: {info.filename}")
            if any(part in IGNORED_NAMES for part in path.parts) or path.suffix.lower() in IGNORED_SUFFIXES:
                raise RuntimeError(f"excluded artifact present: {info.filename}")
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"CRC failure: {bad}")

        expected_verify_parent = (ROOT / "review" / "R01").resolve()
        if VERIFY_TEMP.resolve().parent != expected_verify_parent:
            raise RuntimeError("unsafe verification path")
        if VERIFY_TEMP.exists():
            shutil.rmtree(VERIFY_TEMP)
        VERIFY_TEMP.mkdir(parents=True)
        try:
            extract_root = VERIFY_TEMP
            archive.extractall(extract_root)
            extracted = extract_root / PACKAGE_NAME
            manifest_path = extracted / "SHA256SUMS.txt"
            declared: dict[str, str] = {}
            for line in manifest_path.read_text(encoding="utf-8").splitlines():
                digest, relative = line.split("  ", 1)
                if relative in declared:
                    raise RuntimeError(f"duplicate manifest entry: {relative}")
                declared[relative] = digest
            actual = {
                path.relative_to(extracted).as_posix(): sha256(path)
                for path in extracted.rglob("*")
                if path.is_file() and path != manifest_path
            }
            missing = sorted(set(declared) - set(actual))
            undeclared = sorted(set(actual) - set(declared))
            mismatched = sorted(name for name in declared.keys() & actual.keys() if declared[name] != actual[name])
            if missing or undeclared or mismatched:
                raise RuntimeError(
                    f"manifest failure missing={missing} undeclared={undeclared} mismatched={mismatched}"
                )
        finally:
            shutil.rmtree(VERIFY_TEMP)
        return {
            "entries": len(infos),
            "payloads": len(declared),
            "missing": 0,
            "undeclared": 0,
            "mismatched": 0,
            "crc": "PASS",
            "safe_extraction": "PASS",
        }


def main() -> None:
    if sha256(ORIGINAL_ZIP) != ORIGINAL_SHA256:
        raise SystemExit("original C01 review ZIP changed")
    build_stage()
    build_zip()
    result = verify_zip()
    zip_hash = sha256(ZIP_PATH)
    report = [
        "CONTRACT=CDH-C01-REWORK-002",
        f"ZIP={ZIP_PATH}",
        f"ZIP_SIZE={ZIP_PATH.stat().st_size}",
        f"ZIP_SHA256={zip_hash}",
        f"ZIP_ENTRY_COUNT={result['entries']}",
        f"MANIFEST_PAYLOAD_COUNT={result['payloads']}",
        f"MANIFEST_MISSING={result['missing']}",
        f"MANIFEST_UNDECLARED={result['undeclared']}",
        f"MANIFEST_MISMATCH={result['mismatched']}",
        f"CRC={result['crc']}",
        f"SAFE_EXTRACTION={result['safe_extraction']}",
        f"ORIGINAL_C01_SHA256={ORIGINAL_SHA256}",
    ]
    VERIFY_REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
