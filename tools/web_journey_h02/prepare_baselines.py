"""Safely verify and extract immutable A06/B06 review baselines for H02."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "review" / "H02" / "baselines"
READBACK = ROOT / "review" / "H02" / "BASELINE_READBACK.json"
SPECS = {
    "A06": {
        "zip": ROOT / "review" / "releases" / "CDH_A06_001_REVIEW.zip",
        "sha256": "d9fce75d876b86d5cbb28f77e8ff9354e9d38a5c9389abe10d2a2ddc46adefb5",
        "manifest": "SHA256_MANIFEST.json",
        "kind": "files",
    },
    "B06": {
        "zip": ROOT / "review" / "releases" / "CDH_B06_001_REVIEW.zip",
        "sha256": "d99284c7e6d422b16255b51d29aacb5034a1d43b254c4aca6fa389cef6caf3ae",
        "manifest": "REVIEW_MANIFEST.json",
        "kind": "payloads",
    },
}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def safe_name(name: str) -> bool:
    if "\\" in name or "\x00" in name:
        return False
    value = PurePosixPath(name)
    return not value.is_absolute() and ".." not in value.parts and not (value.parts and ":" in value.parts[0])


def validate_archive(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        bad_crc = archive.testzip()
        infos = archive.infolist()
        names = [item.filename for item in infos]
        lowered = [name.casefold() for name in names]
        symlinks = [item.filename for item in infos if stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF)]
        unsafe = [name for name in names if not safe_name(name)]
        if bad_crc or len(names) != len(set(names)) or len(lowered) != len(set(lowered)) or symlinks or unsafe:
            raise RuntimeError(f"unsafe archive {path.name}: crc={bad_crc} symlink={symlinks} unsafe={unsafe}")
        return {
            "entry_count": len(names),
            "crc": "PASS",
            "duplicate_count": len(names) - len(set(names)),
            "case_collision_count": len(lowered) - len(set(lowered)),
            "symlink_count": len(symlinks),
            "unsafe_path_count": len(unsafe),
        }


def verify_manifest(target: Path, manifest_name: str, kind: str) -> dict[str, object]:
    manifest = json.loads((target / manifest_name).read_text(encoding="utf-8"))
    if kind == "files":
        expected = {item["path"]: (item["sha256"], item["size"]) for item in manifest["files"]}
    else:
        expected = {name: (sha, None) for name, sha in manifest["payloads"].items()}
    missing: list[str] = []
    mismatch: list[str] = []
    for name, (sha256, size) in expected.items():
        file = target / Path(*PurePosixPath(name).parts)
        if not file.is_file():
            missing.append(name)
            continue
        if digest(file) != sha256 or (size is not None and file.stat().st_size != size):
            mismatch.append(name)
    return {
        "declared_count": len(expected),
        "missing_count": len(missing),
        "mismatch_count": len(mismatch),
        "pass": not missing and not mismatch,
    }


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, object] = {}
    for label, spec in SPECS.items():
        source = Path(spec["zip"])
        actual = digest(source)
        if actual != spec["sha256"]:
            raise RuntimeError(f"{label} SHA-256 mismatch: {actual}")
        archive_result = validate_archive(source)
        target = OUTPUT / label
        state = "EXISTING_VERIFIED"
        if not target.exists():
            target.mkdir(parents=True)
            with zipfile.ZipFile(source) as archive:
                archive.extractall(target)
            state = "EXTRACTED"
        manifest_result = verify_manifest(target, str(spec["manifest"]), str(spec["kind"]))
        if not manifest_result["pass"]:
            raise RuntimeError(f"{label} extracted manifest mismatch")
        results[label] = {
            "source": str(source),
            "expected_sha256": spec["sha256"],
            "actual_sha256": actual,
            "state": state,
            "archive": archive_result,
            "manifest": manifest_result,
        }
    summary = {"status": "PASS", "baselines": results}
    READBACK.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

