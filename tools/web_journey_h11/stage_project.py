from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
H11 = ROOT / "review" / "H11"
PROJECT = H11 / "runtime" / "project"
RELEASES = ROOT / "review" / "releases"
A15 = RELEASES / "CDH_A_R12_001_REVIEW.zip"
B16 = RELEASES / "CDH_B_R12_002_REVIEW.zip"
A15_PREFIX = "CDH_A_R12_001_REVIEW/"
B16_PREFIX = "CDH_B_R12_002_REVIEW/"
BASELINES = (
    "CDH_A_R08_001_REVIEW.zip",
    "CDH_B_R07_001_REVIEW.zip",
    "CDH_B_R09_001_REVIEW.zip",
    "CDH_B_R10_001_REVIEW.zip",
    "CDH_C_R10_002_REVIEW.zip",
    "CDH_B_R11_002_REVIEW.zip",
    "CDH_A_R11_004_REVIEW.zip",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_member(info: zipfile.ZipInfo, prefix: str) -> Path | None:
    if not info.filename.startswith(prefix) or info.is_dir():
        return None
    relative = PurePosixPath(info.filename[len(prefix):])
    if relative.is_absolute() or ".." in relative.parts or "\\" in info.filename:
        raise RuntimeError(f"unsafe archive member: {info.filename}")
    if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
        raise RuntimeError(f"symlink archive member: {info.filename}")
    return Path(*relative.parts)


def extract_prefix(archive_path: Path, prefix: str, destination: Path, wanted: tuple[str, ...]) -> int:
    count = 0
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f"CRC failure: {archive_path}")
        for info in archive.infolist():
            relative = safe_member(info, prefix)
            if relative is None or not any(relative.as_posix().startswith(item) for item in wanted):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            count += 1
    return count


def main() -> None:
    if PROJECT.exists():
        raise RuntimeError("H11 staged project already exists")
    PROJECT.mkdir(parents=True)
    a15_count = extract_prefix(A15, A15_PREFIX, PROJECT, ("apps/price-web/",))
    examples = H11 / "runtime" / "examples"
    examples.mkdir(parents=True)
    b16_count = extract_prefix(B16, B16_PREFIX, examples, ("services/private_batch_import_b16/examples/",))
    release_root = PROJECT / "review" / "releases"
    release_root.mkdir(parents=True)
    baseline_hashes = {}
    for name in BASELINES:
        source = RELEASES / name
        target = release_root / name
        shutil.copyfile(source, target)
        baseline_hashes[name] = sha256(target)
    shutil.copyfile(B16, release_root / "CDH_B_R12_001_REVIEW.zip")
    shutil.copyfile(B16, release_root / "CDH_B_R12_002_REVIEW.zip")
    preview_root = PROJECT / "apps" / "price-web" / "local-preview-a11"
    exact_preview = preview_root / "preview_server.py"
    exact_preview.rename(preview_root / "preview_server_a15.py")
    shutil.copyfile(ROOT / "tools" / "web_journey_h11" / "preview_server_h11.py", exact_preview)
    result = {
        "task_id": "H11",
        "status": "PASS",
        "project_root": PROJECT.relative_to(ROOT).as_posix(),
        "a15_extracted_file_count": a15_count,
        "b16_example_file_count": b16_count,
        "a15_release_sha256": sha256(A15),
        "b16_rev2_release_sha256": sha256(B16),
        "b16_runtime_alias_sha256": sha256(release_root / "CDH_B_R12_001_REVIEW.zip"),
        "harness_overlay": "H_OWNED_LOADER_ONLY_NO_A15_SOURCE_CHANGE",
        "exact_a15_preview_server_sha256": sha256(preview_root / "preview_server_a15.py"),
        "baseline_hashes": baseline_hashes,
        "vitest_temp_count": sum(1 for item in PROJECT.rglob("*") if ".vitest-temp" in item.parts),
    }
    (H11 / "STAGED_PROJECT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
