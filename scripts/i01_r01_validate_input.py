from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import stat
import zipfile
from pathlib import Path


EXPECTED_AUDIT_SHA256 = "6a9ce3ddda79be8fab0e590d96b2fea4eb5d226c0780f530e7adc420b370555a"
EXPECTED_I01_RELEASE_SHA256 = "cbeec7d484ee4ef03995d5f5d18dd98dc0644d9296b1414635ef18d4319baef6"
AUDIT_ZIP = Path("input/orchestrator_audits/I01_001/CDH_I01_ORCHESTRATOR_AUDIT_001.zip")
HISTORICAL_RELEASE = Path("review/releases/CDH_I01_001_REVIEW.zip")


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
    result: dict[str, object] = {
        "task_id": "CDH-I01-REWORK-002",
        "audit_zip": AUDIT_ZIP.as_posix(),
        "audit_zip_sha256": sha256(AUDIT_ZIP),
        "historical_release": HISTORICAL_RELEASE.as_posix(),
        "historical_release_sha256": sha256(HISTORICAL_RELEASE),
    }
    with zipfile.ZipFile(AUDIT_ZIP) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos if not item.is_dir()]
        unsafe = []
        symlinks = []
        collisions = []
        seen: set[str] = set()
        for item in infos:
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
        manifest_name = next(name for name in names if name.endswith("/SHA256SUMS.txt"))
        prefix = manifest_name[: -len("SHA256SUMS.txt")]
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
            if name != manifest_name
        }
        missing = sorted(set(declarations) - set(payloads))
        undeclared = sorted(set(payloads) - set(declarations))
        mismatched = sorted(
            name for name in set(declarations) & set(payloads) if declarations[name] != payloads[name]
        )
    result.update(
        {
            "entry_count": len(infos),
            "manifest_declared_count": len(declarations),
            "unsafe": unsafe,
            "symlinks": symlinks,
            "case_collisions": collisions,
            "crc_failure": crc_failure,
            "missing": missing,
            "undeclared": undeclared,
            "mismatched": mismatched,
        }
    )
    passed = (
        result["audit_zip_sha256"] == EXPECTED_AUDIT_SHA256
        and result["historical_release_sha256"] == EXPECTED_I01_RELEASE_SHA256
        and not any((unsafe, symlinks, collisions, missing, undeclared, mismatched))
        and crc_failure is None
    )
    result["status"] = "PASS" if passed else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
