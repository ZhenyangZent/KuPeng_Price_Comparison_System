from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOTS = (
    Path("src/cdh_integration"),
    Path("tests/i01"),
    Path("fixtures/i01"),
    Path("reports/I01/001"),
    Path("review/I01/001/evidence"),
    Path("review/I01/001/logs"),
    Path("input/orchestrator_bundles/I01"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    scripts = sorted(Path("scripts").glob("*i01*.py")) + [Path("scripts/generate_i01_fixtures.py")]
    paths: set[Path] = set(scripts)
    for root in ROOTS:
        if root.exists():
            paths.update(path for path in root.rglob("*") if path.is_file())
    paths = {
        path
        for path in paths
        if "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and path.as_posix() != "reports/I01/001/CHANGE_MANIFEST.csv"
    }
    output = Path("reports/I01/001/CHANGE_MANIFEST.csv")
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("path", "change_type", "bytes", "sha256"))
        for path in sorted(paths):
            writer.writerow((path.as_posix(), "ADDED_I01", path.stat().st_size, sha256(path)))
    print(f"CHANGE_MANIFEST_ROWS={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

