from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


SOURCES = {
    "A16_REV2": ("CDH_A_R12_004_REVIEW.zip", "8eba2b5059c92fcd71897ee345527c78741ebe6c3230c45eab87dd4921b339e4"),
    "B11_R07": ("CDH_B_R07_001_REVIEW.zip", "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"),
    "B13_R09": ("CDH_B_R09_001_REVIEW.zip", "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638"),
    "B14_R10": ("CDH_B_R10_001_REVIEW.zip", "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9"),
    "C11_REV2_R10": ("CDH_C_R10_002_REVIEW.zip", "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa"),
    "A14_R11": ("CDH_A_R11_004_REVIEW.zip", "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160"),
    "B15_REV2": ("CDH_B_R11_002_REVIEW.zip", "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe"),
    "B16_REV3": ("CDH_B_R12_003_REVIEW.zip", "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7"),
}
BASELINE_ROLES = ("B11_R07", "B13_R09", "B14_R10", "C11_REV2_R10", "A14_R11", "B15_REV2")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sources(release_root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for role, (name, expected) in SOURCES.items():
        path = (release_root / name).resolve(strict=True)
        if not path.is_relative_to(release_root) or path.is_symlink() or not path.is_file():
            raise RuntimeError(f"SOURCE_RELEASE_UNSAFE: {role}")
        actual = sha256_file(path)
        if not secrets.compare_digest(actual, expected):
            raise RuntimeError(f"SOURCE_RELEASE_SHA256_MISMATCH: {role} expected={expected} actual={actual}")
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise RuntimeError(f"SOURCE_RELEASE_CRC_FAILURE: {role} member={bad}")
        result[role] = path
    return result


def safe_relative(name: str, prefix: str) -> Path | None:
    normalized = name.replace("\\", "/")
    if not normalized.startswith(prefix) or normalized.endswith("/"):
        return None
    value = PurePosixPath(normalized[len(prefix) :])
    if not value.parts or value.is_absolute() or any(part in {"", ".", ".."} for part in value.parts):
        raise RuntimeError(f"UNSAFE_ARCHIVE_MEMBER: {name}")
    return Path(*value.parts)


def extract_prefix(archive_path: Path, prefix: str, destination: Path) -> int:
    count = 0
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            relative = safe_relative(info.filename, prefix)
            if relative is None:
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RuntimeError(f"ARCHIVE_LINK_REFUSED: {info.filename}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            count += 1
    if count == 0:
        raise RuntimeError(f"ARCHIVE_PREFIX_EMPTY: {archive_path.name} {prefix}")
    return count


def build(project_root: Path, replace_generated: bool) -> dict[str, object]:
    root = project_root.resolve(strict=True)
    bundle = root / "apps" / "price-web" / "local-trial-a17"
    release_root = (root / "review" / "releases").resolve(strict=True)
    sources = verify_sources(release_root)
    vendor = bundle / "vendor"
    manifest_path = bundle / "A17_RUNTIME_MANIFEST.json"
    if vendor.exists():
        if not replace_generated:
            raise RuntimeError("A17_VENDOR_EXISTS: use --replace-generated after reviewing the existing manifest")
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise RuntimeError("A17_VENDOR_NOT_PROVEN_GENERATED") from exc
        if existing.get("schema_version") != "CDH-A17-RUNTIME-BUNDLE-MANIFEST-1":
            raise RuntimeError("A17_VENDOR_NOT_PROVEN_GENERATED")
        shutil.rmtree(vendor)
    staging = bundle / f".vendor-staging-{os.getpid()}"
    if staging.exists():
        raise RuntimeError(f"A17_STAGING_EXISTS: {staging}")
    try:
        extract_prefix(
            sources["A16_REV2"],
            "CDH_A_R12_004_REVIEW/apps/price-web/frontend/dist/",
            staging / "frontend" / "dist",
        )
        extract_prefix(
            sources["B11_R07"],
            "CDH_B_R07_001_REVIEW/services/price_coupon_v4/",
            staging / "b11",
        )
        extract_prefix(
            sources["B16_REV3"],
            "CDH_B_R12_003_REVIEW/services/private_observation_b15/",
            staging / "b16" / "private_observation_b15",
        )
        extract_prefix(
            sources["B16_REV3"],
            "CDH_B_R12_003_REVIEW/services/private_batch_import_b16/",
            staging / "b16" / "private_batch_import_b16",
        )
        baseline_root = staging / "baselines"
        baseline_root.mkdir(parents=True, exist_ok=True)
        for role in BASELINE_ROLES:
            shutil.copyfile(sources[role], baseline_root / SOURCES[role][0])
        files = [
            {
                "path": item.relative_to(staging).as_posix(),
                "size": item.stat().st_size,
                "sha256": sha256_file(item),
            }
            for item in sorted(staging.rglob("*"))
            if item.is_file()
        ]
        os.replace(staging, vendor)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    manifest = {
        "schema_version": "CDH-A17-RUNTIME-BUNDLE-MANIFEST-1",
        "source_releases": {
            role: {"filename": SOURCES[role][0], "sha256": SOURCES[role][1]} for role in sorted(SOURCES)
        },
        "files": files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "PASS",
        "bundle": str(bundle),
        "file_count": len(files),
        "manifest_sha256": sha256_file(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the hash-bound A17 Windows trial runtime bundle")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--replace-generated", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.project_root, args.replace_generated), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
