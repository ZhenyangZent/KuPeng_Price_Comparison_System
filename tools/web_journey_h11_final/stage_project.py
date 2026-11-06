from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "review" / "H11_FINAL"
PROJECT = FINAL / "runtime" / "project"
RELEASES = ROOT / "review" / "releases"
A15 = RELEASES / "CDH_A_R12_002_REVIEW.zip"
B16 = RELEASES / "CDH_B_R12_003_REVIEW.zip"
A15_PREFIX = "CDH_A_R12_002_REVIEW/"
B16_PREFIX = "CDH_B_R12_003_REVIEW/"
BASELINES = (
    "CDH_A_R08_001_REVIEW.zip", "CDH_B_R07_001_REVIEW.zip",
    "CDH_B_R09_001_REVIEW.zip", "CDH_B_R10_001_REVIEW.zip",
    "CDH_C_R10_002_REVIEW.zip", "CDH_B_R11_002_REVIEW.zip",
    "CDH_A_R11_004_REVIEW.zip",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract(archive_path: Path, prefix: str, destination: Path, wanted: tuple[str, ...]) -> int:
    count = 0
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f"CRC failure: {archive_path}")
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            relative = PurePosixPath(info.filename[len(prefix):])
            if relative.is_absolute() or ".." in relative.parts or "\\" in info.filename or stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
                raise RuntimeError(f"unsafe archive member: {info.filename}")
            if not any(relative.as_posix().startswith(item) for item in wanted):
                continue
            target = destination / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            count += 1
    return count


def main() -> None:
    if PROJECT.exists():
        raise RuntimeError("H11 final staged project already exists")
    PROJECT.mkdir(parents=True)
    a15_count = extract(A15, A15_PREFIX, PROJECT, ("apps/price-web/",))
    examples = FINAL / "runtime" / "examples"
    examples.mkdir(parents=True)
    example_count = extract(B16, B16_PREFIX, examples, ("services/private_batch_import_b16/examples/",))
    release_root = PROJECT / "review" / "releases"
    release_root.mkdir(parents=True)
    hashes = {}
    for name in BASELINES:
        shutil.copyfile(RELEASES / name, release_root / name)
        hashes[name] = sha256(release_root / name)
    shutil.copyfile(B16, release_root / "CDH_B_R12_003_REVIEW.zip")
    preview = PROJECT / "apps" / "price-web" / "local-preview-a11" / "preview_server.py"
    control = preview.with_name("control.py")
    preview_text = preview.read_text(encoding="utf-8")
    control_text = control.read_text(encoding="utf-8")
    required = ("CDH_B_R12_003_REVIEW.zip", "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7", "CDH_B_R12_003_REVIEW/services/")
    control_binding = (
        required[0] in control_text
        and 'verify_pinned_release(b16, B16_SHA256, "B16_R12_REV3")' in control_text
    )
    binding_gate = all(item in preview_text for item in required) and control_binding
    loader_count = sum(1 for item in PROJECT.rglob("*") if item.is_file() and item.name in {"preview_server_a15.py", "preview_server_h11.py"})
    result = {
        "task_id": "H11", "revision": "FINAL_OFFICIAL_LAUNCHER", "status": "PASS" if binding_gate and loader_count == 0 else "FAIL",
        "project_root": PROJECT.relative_to(ROOT).as_posix(), "a15_extracted_file_count": a15_count,
        "b16_example_file_count": example_count, "a15_rev2_sha256": sha256(A15), "b16_rev3_sha256": sha256(B16),
        "official_preview_server_sha256": sha256(preview), "official_control_sha256": sha256(control),
        "official_binding_gate": binding_gate, "h_test_loader_file_count": loader_count,
        "baseline_hashes": hashes, "vitest_temp_count": sum(1 for item in PROJECT.rglob("*") if ".vitest-temp" in item.parts),
    }
    (FINAL / "STAGED_PROJECT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
