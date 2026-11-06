from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED = {
    "B14": ("CDH_B_R10_001_REVIEW.zip", "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9"),
    "C11_REV2": ("CDH_C_R10_002_REVIEW.zip", "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa"),
    "B11": ("CDH_B_R07_001_REVIEW.zip", "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"),
}


class BaselineError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_baselines(release_root: Path) -> dict[str, str]:
    root = release_root.resolve()
    if not root.is_dir() or release_root.is_symlink():
        raise BaselineError("baseline root must be a regular local directory")
    result: dict[str, str] = {}
    for role, (name, expected) in EXPECTED.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
            raise BaselineError(f"{role} baseline missing")
        actual = _sha256(path)
        if actual != expected:
            raise BaselineError(f"{role} baseline SHA-256 mismatch")
        result[role] = actual
    return result
