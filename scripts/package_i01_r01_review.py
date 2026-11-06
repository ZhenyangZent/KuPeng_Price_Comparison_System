from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PACKAGE_NAME = "CDH_I01_R01_REVIEW"
STAGE = Path("review/I01/R01/package") / PACKAGE_NAME
TARGET = Path("review/releases/CDH_I01_R01_REVIEW.zip")
ARTIFACT_TEMP = Path("review/I01/R01/tmp/package_artifacts")
PREFLIGHT_ZIP = ARTIFACT_TEMP / "CDH_I01_R01_PREFLIGHT.zip"
PREFLIGHT_EXTRACT = ARTIFACT_TEMP / "preflight_extract"
FINAL_EXTRACT = ARTIFACT_TEMP / "final_extract"
PACKAGE_LOGS = Path("review/I01/R01/logs/package")
FINAL_EVIDENCE = Path("review/I01/R01/evidence/final")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def excluded(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


def copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    for path in source.rglob("*"):
        if not path.is_file() or excluded(path):
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def stage_payload() -> None:
    if STAGE.exists() or TARGET.exists() or ARTIFACT_TEMP.exists() or PACKAGE_LOGS.exists():
        raise FileExistsError("I01-R01 package output already exists; refusing to overwrite")
    STAGE.mkdir(parents=True)
    ARTIFACT_TEMP.mkdir(parents=True)
    PACKAGE_LOGS.mkdir(parents=True)
    mappings = (
        (Path("src/cdh_core"), STAGE / "src/cdh_core"),
        (Path("src/cdh_integration"), STAGE / "src/cdh_integration"),
        (Path("tests/fixtures"), STAGE / "tests/fixtures"),
        (Path("tests/i01"), STAGE / "tests/i01"),
        (Path("tests/b01"), STAGE / "tests/b01"),
        (Path("experiments/B01/extension"), STAGE / "experiments/B01/extension"),
        (Path("fixtures/i01"), STAGE / "fixtures/i01"),
        (Path("reports/I01/001"), STAGE / "reports/I01/001"),
        (Path("reports/I01/R01"), STAGE / "reports/I01/R01"),
        (Path("review/I01/R01/evidence"), STAGE / "review/I01/R01/evidence"),
        (Path("review/I01/R01/logs"), STAGE / "review/I01/R01/logs"),
        (Path("input/orchestrator_bundles/I01"), STAGE / "input/orchestrator_bundles/I01"),
        (Path("input/orchestrator_audits/I01_001"), STAGE / "input/orchestrator_audits/I01_001"),
    )
    for source, destination in mappings:
        copy_tree(source, destination)
    for path in sorted(Path("tests").glob("test_*.py")):
        target = STAGE / "tests" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    scripts = set(Path("scripts").glob("*i01*.py")) | {Path("scripts/generate_i01_fixtures.py")}
    for path in sorted(scripts):
        target = STAGE / "scripts" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for path in (Path("pyproject.toml"), Path("README.md")):
        shutil.copy2(path, STAGE / path.name)


def write_manifest() -> tuple[int, str]:
    manifest = STAGE / "SHA256SUMS.txt"
    payloads = sorted(path for path in STAGE.rglob("*") if path.is_file() and path != manifest)
    manifest.write_text(
        "\n".join(f"{sha256(path)}  {path.relative_to(STAGE).as_posix()}" for path in payloads) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(payloads), sha256(manifest)


def make_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(item for item in STAGE.rglob("*") if item.is_file()):
            archive.write(file, f"{PACKAGE_NAME}/{file.relative_to(STAGE).as_posix()}")


def validate_zip(path: Path, extract_root: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        unsafe: list[str] = []
        collisions: list[str] = []
        symlinks: list[str] = []
        seen: set[str] = set()
        total_uncompressed = 0
        for item in infos:
            total_uncompressed += item.file_size
            normalized = posixpath.normpath(item.filename.replace("\\", "/"))
            if (
                item.filename.startswith(("/", "\\"))
                or normalized == ".."
                or normalized.startswith("../")
                or ":" in normalized
                or "\\" in item.filename
            ):
                unsafe.append(item.filename)
            folded = normalized.casefold()
            if folded in seen:
                collisions.append(item.filename)
            seen.add(folded)
            if stat.S_ISLNK(item.external_attr >> 16):
                symlinks.append(item.filename)
        crc_failure = archive.testzip()
        prefix = f"{PACKAGE_NAME}/"
        manifest_name = prefix + "SHA256SUMS.txt"
        declarations: dict[str, str] = {}
        for line in archive.read(manifest_name).decode("utf-8-sig").splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(r"([0-9a-f]{64})\s+\*?(.+)", line)
            if match is None:
                raise ValueError(f"invalid manifest line: {line!r}")
            declarations[match.group(2)] = match.group(1)
        payloads = {
            name[len(prefix) :]: hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name.startswith(prefix) and name != manifest_name and not name.endswith("/")
        }
        missing = sorted(set(declarations) - set(payloads))
        undeclared = sorted(set(payloads) - set(declarations))
        mismatched = sorted(
            name for name in set(declarations) & set(payloads) if declarations[name] != payloads[name]
        )
        extract_root.mkdir(parents=True)
        base = extract_root.resolve()
        for item in infos:
            destination = (extract_root / item.filename).resolve()
            if destination != base and base not in destination.parents:
                raise ValueError(f"unsafe extraction target: {item.filename}")
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(item))
    extracted = extract_root / PACKAGE_NAME
    extracted_mismatch = sorted(
        name for name, digest in declarations.items() if not (extracted / name).is_file() or sha256(extracted / name) != digest
    )
    passed = not any((unsafe, collisions, symlinks, missing, undeclared, mismatched, extracted_mismatch)) and crc_failure is None
    return {
        "zip": path.as_posix(),
        "zip_sha256": sha256(path),
        "zip_bytes": path.stat().st_size,
        "entry_count": len(names),
        "total_uncompressed_bytes": total_uncompressed,
        "payload_count": len(payloads),
        "manifest_declared_count": len(declarations),
        "unsafe": unsafe,
        "case_collisions": collisions,
        "symlinks": symlinks,
        "crc_failure": crc_failure,
        "missing": missing,
        "undeclared": undeclared,
        "mismatched": mismatched,
        "extracted_mismatch": extracted_mismatch,
        "pass": passed,
    }


def run_tests(extracted: Path, label: str) -> dict[str, object]:
    test_temp = extracted / "review/I01/R01/tmp/package_tests"
    test_temp.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    c01 = [
        "tests.test_history_policy",
        "tests.test_models_pricing",
        "tests.test_orchestrator_r01_new_regressions",
        "tests.test_persistence_demo",
        "tests.test_r02_positive_regressions",
        "tests.test_r03_policy_fee_coupon_regressions",
        "tests.test_r04_expiry_provenance_authority",
        "tests.test_rework_regressions",
    ]
    commands = (
        ("c01", [python, "-B", "-m", "unittest", "-v", *c01], 143),
        ("b01_node", ["node", "--test", "tests/b01/test_extension_logic.mjs", "tests/b01/test_native_port_recovery.mjs", "tests/b01/test_native_response_validation.mjs"], 26),
        ("i01_original", [python, "-B", "-m", "unittest", "-v", "tests.i01.test_adapter_pipeline"], 44),
        ("orchestrator_11", [python, "-B", "-m", "unittest", "-v", "tests.i01.test_i01_orchestrator_new"], 11),
        ("i01_r01_added", [python, "-B", "-m", "unittest", "-v", "tests.i01.test_i01_r01_regressions"], 13),
    )
    results: list[dict[str, object]] = []
    for name, command, expected in commands:
        completed = subprocess.run(
            command,
            cwd=extracted,
            env={
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": "src;.",
                "TEMP": "review/I01/R01/tmp/package_tests",
                "TMP": "review/I01/R01/tmp/package_tests",
            },
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        (PACKAGE_LOGS / f"{label}_{name}.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (PACKAGE_LOGS / f"{label}_{name}.stderr.log").write_text(completed.stderr, encoding="utf-8")
        matches = re.findall(r"Ran (\d+) tests|(?:#|ℹ) tests (\d+)", completed.stdout + "\n" + completed.stderr)
        actual = int(next(value for value in matches[-1] if value)) if matches else None
        results.append(
            {
                "suite": name,
                "exit_code": completed.returncode,
                "expected_tests": expected,
                "actual_tests": actual,
                "pass": completed.returncode == 0 and actual == expected,
            }
        )
    return {
        "label": label,
        "suites": results,
        "test_total": sum(int(item["actual_tests"] or 0) for item in results),
        "pass": all(bool(item["pass"]) for item in results),
    }


def main() -> int:
    stage_payload()
    write_manifest()
    make_zip(PREFLIGHT_ZIP)
    preflight_integrity = validate_zip(PREFLIGHT_ZIP, PREFLIGHT_EXTRACT)
    preflight_tests = run_tests(PREFLIGHT_EXTRACT / PACKAGE_NAME, "preflight")
    preflight = {
        "task_id": "CDH-I01-REWORK-002",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "integrity": preflight_integrity,
        "tests": preflight_tests,
        "status": "PASS" if preflight_integrity["pass"] and preflight_tests["pass"] else "FAIL",
    }
    if preflight["status"] != "PASS":
        raise RuntimeError("package preflight failed")
    preflight_text = json.dumps(preflight, ensure_ascii=False, indent=2) + "\n"
    (FINAL_EVIDENCE / "PACKAGE_PREFLIGHT.json").write_text(preflight_text, encoding="utf-8")
    staged_preflight = STAGE / "review/I01/R01/evidence/final/PACKAGE_PREFLIGHT.json"
    staged_preflight.parent.mkdir(parents=True, exist_ok=True)
    staged_preflight.write_text(preflight_text, encoding="utf-8")
    copy_tree(PACKAGE_LOGS, STAGE / "review/I01/R01/logs/package")
    payload_count, manifest_hash = write_manifest()
    make_zip(TARGET)
    final_integrity = validate_zip(TARGET, FINAL_EXTRACT)
    final_tests = run_tests(FINAL_EXTRACT / PACKAGE_NAME, "final")
    final = {
        "task_id": "CDH-I01-REWORK-002",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload_count": payload_count,
        "manifest_sha256": manifest_hash,
        "integrity": final_integrity,
        "tests": final_tests,
        "status": "PASS" if final_integrity["pass"] and final_tests["pass"] else "FAIL",
    }
    (FINAL_EVIDENCE / "FINAL_ZIP_VALIDATION.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0 if final["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
