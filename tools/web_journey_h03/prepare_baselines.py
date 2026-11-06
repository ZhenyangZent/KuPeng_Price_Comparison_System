"""Safely extract exact A07/B08 and arrived A08/B09 baselines for H03."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "review" / "H03" / "baselines"
READBACK = ROOT / "review" / "H03" / "BASELINE_READBACK.json"
SPECS = {
    "A07": {
        "zip": ROOT / "review" / "releases" / "CDH_A07_001_REVIEW.zip",
        "sha256": "390499b3c99b2d3b551530be357f2810d6299db7c8cbd8ab182cf8ca2e19db90",
        "manifest": "CDH_A07_001_REVIEW/MANIFEST.json",
        "kind": "files_relative_to_package",
    },
    "B08": {
        "zip": ROOT / "review" / "releases" / "CDH_B08_001_REVIEW.zip",
        "sha256": "a6d5ffb65860fcb33504baefd3c5288c1c75aac0494af248bb3e4c5624cd69bd",
        "manifest": "CDH_B08_001_REVIEW/REVIEW_MANIFEST.json",
        "kind": "payload_list",
    },
    "A08": {
        "zip": ROOT / "review" / "releases" / "CDH_A08_001_REVIEW.zip",
        "sha256": "5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d",
        "manifest": "CDH_A08_001_REVIEW/MANIFEST.json",
        "kind": "files_relative_to_package",
    },
    "B09": {
        "zip": ROOT / "review" / "releases" / "CDH_B09_001_REVIEW.zip",
        "sha256": "10f7ae283108b460ce533b52b75ba1698218632b38d5b58fbda8e643b9234bab",
        "manifest": "CDH_B09_001_REVIEW/REVIEW_MANIFEST.json",
        "kind": "payload_list",
    },
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def safe_name(name: str) -> bool:
    value = PurePosixPath(name)
    return "\\" not in name and not value.is_absolute() and ".." not in value.parts and not (value.parts and ":" in value.parts[0])


def archive_gate(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        infos = archive.infolist()
        names = [item.filename for item in infos]
        folded = [name.casefold() for name in names]
        symlinks = [item.filename for item in infos if stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF)]
        unsafe = [name for name in names if not safe_name(name)]
        if bad or len(names) != len(set(names)) or len(folded) != len(set(folded)) or symlinks or unsafe:
            raise RuntimeError(f"unsafe archive: {path.name}")
        return {"entries": len(names), "crc": "PASS", "duplicates": 0, "case_collisions": 0, "symlinks": 0, "unsafe_paths": 0}


def manifest_gate(target: Path, spec: dict[str, object]) -> dict[str, object]:
    manifest = json.loads((target / str(spec["manifest"])).read_text(encoding="utf-8"))
    if spec["kind"] == "files_relative_to_package":
        root = (target / str(spec["manifest"])).parent
        expected = [(item["path"], item["sha256"], item["size"]) for item in manifest["files"]]
    else:
        root = target
        expected = [(item["path"], item["sha256"], item["bytes"]) for item in manifest["payloads"]]
    mismatch = []
    for name, sha256, size in expected:
        file = root / Path(*PurePosixPath(name).parts)
        if not file.is_file() or file.stat().st_size != size or digest(file) != sha256:
            mismatch.append(name)
    return {"declared": len(expected), "mismatch": len(mismatch), "pass": not mismatch}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for label, spec in SPECS.items():
        source = Path(spec["zip"])
        actual = digest(source)
        if actual != spec["sha256"]:
            raise RuntimeError(f"{label} SHA-256 mismatch: {actual}")
        archive = archive_gate(source)
        target = OUT / label
        state = "EXISTING_VERIFIED"
        if not target.exists():
            target.mkdir(parents=True)
            with zipfile.ZipFile(source) as value:
                value.extractall(target)
            state = "EXTRACTED"
        manifest = manifest_gate(target, spec)
        if not manifest["pass"]:
            raise RuntimeError(f"{label} manifest mismatch")
        results[label] = {"sha256": actual, "state": state, "archive": archive, "manifest": manifest}
    summary = {"status": "PASS", "baselines": results}
    READBACK.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

