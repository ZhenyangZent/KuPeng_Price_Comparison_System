from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
A13 = ROOT / "review" / "H09" / "baselines" / "A13_REV3" / "CDH_A_R11_003_REVIEW"
RUNTIME = ROOT / "review" / "H09" / "runtime"
PROJECT = RUNTIME / "project"
OUT = ROOT / "review" / "H09" / "STAGED_PROJECT.json"
RELEASES = {
    "CDH_A_R08_001_REVIEW.zip": "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
    "CDH_B_R07_001_REVIEW.zip": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
    "CDH_B_R10_001_REVIEW.zip": "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9",
    "CDH_C_R10_002_REVIEW.zip": "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa",
    "CDH_B_R11_002_REVIEW.zip": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    source = A13 / "apps" / "price-web"
    target = PROJECT / "apps" / "price-web"
    shutil.copytree(source / "frontend" / "dist", target / "frontend" / "dist", dirs_exist_ok=True)
    shutil.copytree(source / "local-preview-a11", target / "local-preview-a11", dirs_exist_ok=True)
    release_target = PROJECT / "review" / "releases"; release_target.mkdir(parents=True, exist_ok=True)
    copied = {}
    for name, expected in RELEASES.items():
        origin = ROOT / "review" / "releases" / name
        if sha256(origin) != expected:
            raise RuntimeError(f"source hash mismatch: {name}")
        destination = release_target / name; shutil.copyfile(origin, destination)
        if sha256(destination) != expected:
            raise RuntimeError(f"staged hash mismatch: {name}")
        copied[name] = expected
    payload = {
        "task_id": "CDH-H09-A13REV3-B15REV2-WINDOWS-E2E-001",
        "project_root": PROJECT.relative_to(ROOT).as_posix(),
        "source_a13_release_sha256": "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274",
        "control_sha256": sha256(target / "local-preview-a11" / "control.py"),
        "preview_server_sha256": sha256(target / "local-preview-a11" / "preview_server.py"),
        "dist_manifest_sha256": sha256(target / "frontend" / "dist" / "A11_DIST_MANIFEST.json"),
        "release_copies": copied,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
