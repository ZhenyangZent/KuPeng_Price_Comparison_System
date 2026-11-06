from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from .audit import sha256_file


PACKAGE = "CDH_G_R07_001_REVIEW"
INCLUDE = (
    Path("tools/ci_web_g06"), Path("tests/ci_web_g06"), Path("docs/CI_PREVIEW/G06"),
    Path("reports/G06/STATUS.json"), Path("reports/G06/INPUT_VERIFICATION.md"),
    Path("reports/G06/IMPLEMENTATION_SUMMARY.md"), Path("reports/G06/TEST_RESULTS.md"),
    Path("reports/G06/CHANGE_LIST.md"), Path("reports/G06/RISK_REGISTER.md"),
    Path("reports/G06/COMMANDS_AND_EXIT_CODES.md"),
    Path("reports/G06/runs/a09_b10_expected_fail_final3"),
    Path("reports/G06/runs/a10_b11_input_availability_final"),
)


def _inputs(root: Path):
    for requested in INCLUDE:
        source = root / requested
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for candidate in candidates:
            if candidate.is_file() and "__pycache__" not in candidate.parts and candidate.suffix != ".pyc":
                yield candidate, candidate.relative_to(root)


def package(root: Path) -> dict:
    root = root.resolve(); stage = root / "review" / "G06" / "package" / PACKAGE
    if stage.exists(): shutil.rmtree(stage)
    stage.mkdir(parents=True)
    copied = []
    for source, relative in _inputs(root):
        target = stage / relative; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target); copied.append(target)
    payloads = [{"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(copied)]
    manifest = {"schema": "CDH-G06-R07-REVIEW-MANIFEST-1", "task_id": "CDH-G06-EXACT-RELEASE-V4-E2E-CI-001", "payload_count": len(payloads), "payloads": payloads}
    manifest_path = stage / "MANIFEST.json"; manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release = root / "review" / "releases" / f"{PACKAGE}.zip"; release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in sorted(stage.rglob("*")):
            if not source.is_file(): continue
            info = zipfile.ZipInfo((Path(PACKAGE) / source.relative_to(stage)).as_posix(), date_time=(2026, 11, 5, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    upload = root / "review" / "00_TO_UPLOAD" / release.name; upload.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(release, upload)
    return {"release": str(release), "upload": str(upload), "sha256": sha256_file(release), "upload_sha256": sha256_file(upload), "manifest_sha256": sha256_file(manifest_path), "payload_count": len(payloads), "byte_identical": release.read_bytes() == upload.read_bytes()}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path.cwd()); args = parser.parse_args()
    print(json.dumps(package(args.root), ensure_ascii=False, indent=2))
