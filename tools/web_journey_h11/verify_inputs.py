from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "review" / "H11" / "INPUT_READBACK.json"
INPUTS = {
    "A15": ("CDH_A_R12_001_REVIEW.zip", "5cc44dedd910ff9b2055cfc2772ad0c3d6db627ffc818794f81fd3d9b5552d4b", "SHA256_MANIFEST.json"),
    "B16_REV2": ("CDH_B_R12_002_REVIEW.zip", "6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6", "REVIEW_MANIFEST.json"),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe(name: str) -> bool:
    parsed = PurePosixPath(name)
    return "\\" not in name and not parsed.is_absolute() and ".." not in parsed.parts


def inspect(label: str, filename: str, expected: str, manifest_basename: str) -> dict[str, object]:
    path = ROOT / "review" / "releases" / filename
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"{label} SHA-256 mismatch: {actual}")
    prefix = filename.removesuffix(".zip") + "/"
    manifest_name = prefix + manifest_basename
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        bad = archive.testzip()
        manifest_bytes = archive.read(manifest_name)
        manifest = json.loads(manifest_bytes)
        payloads = manifest["payloads"]
        declared: dict[str, dict[str, object]] = {}
        for item in payloads:
            raw = str(item["path"])
            member = raw if raw.startswith(prefix) else prefix + raw
            declared[member] = item
        mismatches = []
        for member, item in declared.items():
            try:
                data = archive.read(member)
            except KeyError:
                mismatches.append(member)
                continue
            if len(data) != int(item["bytes"]) or sha256_bytes(data) != item["sha256"]:
                mismatches.append(member)
        expected_names = set(declared) | {manifest_name}
        unsafe = [name for name in names if not safe(name)]
        symlinks = [item.filename for item in infos if stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF)]
        result = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": actual,
            "bytes": path.stat().st_size,
            "entries": len(names),
            "manifest_path": manifest_name,
            "manifest_sha256": sha256_bytes(manifest_bytes),
            "manifest_declared": len(declared),
            "crc": "PASS" if bad is None else "FAIL",
            "mismatch": len(mismatches),
            "missing": len(expected_names - set(names)),
            "undeclared": len(set(names) - expected_names),
            "duplicates": len(names) - len(set(names)),
            "case_collisions": len(names) - len({name.casefold() for name in names}),
            "unsafe_paths": len(unsafe),
            "symlinks": len(symlinks),
            "api_schema": manifest.get("api_schema"),
            "api_route_or_request_schema_change_count": manifest.get("api_route_or_request_schema_change_count"),
        }
    clean = ("mismatch", "missing", "undeclared", "duplicates", "case_collisions", "unsafe_paths", "symlinks")
    if result["crc"] != "PASS" or any(result[key] != 0 for key in clean):
        raise RuntimeError(f"{label} archive validation failed: {result}")
    return result


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    inputs = {label: inspect(label, *value) for label, value in INPUTS.items()}
    result = {
        "task_id": "H11",
        "status": "PASS",
        "inputs": inputs,
        "api_compatibility_claim": {
            "schema": inputs["B16_REV2"]["api_schema"],
            "route_or_request_schema_change_count": inputs["B16_REV2"]["api_route_or_request_schema_change_count"],
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
