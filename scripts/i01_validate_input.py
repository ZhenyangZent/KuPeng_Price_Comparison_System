from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import zipfile
from pathlib import Path


EXPECTED_INPUT_SHA256 = "3040451b7d99cc2274b7df04672d33d8b89c0b7a91a7810e871cd0ff8cdc3c3b"
EXPECTED_RELEASES = {
    "review/releases/CDH_C01_R04_REVIEW.zip": "cce874a926acf06986e456bdac7e1a93e90611b696ab7917c7bb5cd56e8cdf00",
    "review/releases/CDH_B01_PHASE_B_001_REVIEW.zip": "0718a2ce6603b56e25006f6a35a5a308ba98938092de7d4b44c0b17ccfdc03b6",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    archive = Path("input/orchestrator_bundles/I01/CDH_I01_001_INPUT_BUNDLE.zip")
    extracted = Path("input/orchestrator_bundles/I01/extracted/CDH_I01_001_INPUT_BUNDLE")
    gates: dict[str, dict[str, object]] = {}
    input_hash = sha256(archive)
    gates["INPUT_SHA256"] = {"pass": input_hash == EXPECTED_INPUT_SHA256, "actual": input_hash}
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        names = [item.filename for item in infos]
        unsafe = []
        duplicates = []
        seen: set[str] = set()
        for name in names:
            normalized = posixpath.normpath(name.replace("\\", "/"))
            if name.startswith(("/", "\\")) or normalized == ".." or normalized.startswith("../"):
                unsafe.append(name)
            if re.match(r"^[A-Za-z]:", name):
                unsafe.append(name)
            if name.casefold() in seen:
                duplicates.append(name)
            seen.add(name.casefold())
        crc_failure = bundle.testzip()
        declarations: dict[str, str] = {}
        for line in bundle.read("SHA256SUMS.txt").decode("utf-8-sig").splitlines():
            line = line.strip()
            if line:
                digest, name = line.split(None, 1)
                declarations[name.lstrip("*")] = digest.lower()
        payload_hashes = {
            name: hashlib.sha256(bundle.read(name)).hexdigest()
            for name in names
            if name != "SHA256SUMS.txt" and not name.endswith("/")
        }
        missing = sorted(set(declarations) - set(payload_hashes))
        undeclared = sorted(set(payload_hashes) - set(declarations))
        mismatched = sorted(
            name for name in set(declarations) & set(payload_hashes) if declarations[name] != payload_hashes[name]
        )
        extracted_mismatch = sorted(
            name
            for name, digest in payload_hashes.items()
            if not (extracted / name).is_file() or sha256(extracted / name) != digest
        )
    gates["ZIP_SAFE_PATHS"] = {"pass": not unsafe, "detail": unsafe}
    gates["ZIP_UNIQUE_NAMES"] = {"pass": not duplicates, "detail": duplicates}
    gates["ZIP_CRC"] = {"pass": crc_failure is None, "detail": crc_failure}
    gates["MANIFEST_PAYLOADS"] = {
        "pass": not missing and not undeclared and not mismatched,
        "declared": len(declarations),
        "payloads": len(payload_hashes),
        "missing": missing,
        "undeclared": undeclared,
        "mismatched": mismatched,
    }
    gates["EXTRACTED_CONTENT"] = {"pass": not extracted_mismatch, "mismatched": extracted_mismatch}
    for path_text, expected in EXPECTED_RELEASES.items():
        path = Path(path_text)
        actual = sha256(path) if path.is_file() else None
        gates[f"HISTORICAL_{path.stem}_SHA256"] = {"pass": actual == expected, "actual": actual}
    result = {
        "task_id": "CDH-I01-SYNTHETIC-INTEGRATION-001",
        "input_archive": archive.as_posix(),
        "entry_count": len(names),
        "gates": gates,
        "passed": sum(bool(item["pass"]) for item in gates.values()),
        "failed": sum(not bool(item["pass"]) for item in gates.values()),
    }
    result["status"] = "PASS" if result["failed"] == 0 else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

