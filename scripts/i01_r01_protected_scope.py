from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTECTED_DIRECTORIES = (
    Path("src/cdh_core"),
    Path("experiments/B01"),
    Path("tests/b01"),
    Path("research/G0"),
    Path("tests/g0"),
    Path("fixtures/g0"),
    Path("reports/G0"),
    Path("review/G0"),
    Path("reports/I01/001"),
    Path("review/I01/001"),
    Path("input/orchestrator_bundles/I01"),
    Path("input/orchestrator_audits/I01_001"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect() -> dict[str, object]:
    paths: set[Path] = set()
    for relative in PROTECTED_DIRECTORIES:
        base = PROJECT_ROOT / relative
        if base.exists():
            paths.update(path for path in base.rglob("*") if path.is_file())
    paths.update(path for path in (PROJECT_ROOT / "tests").glob("test_*.py") if path.is_file())
    paths.update(
        path
        for path in (PROJECT_ROOT / "review/releases").glob("*.zip")
        if path.name != "CDH_I01_R01_REVIEW.zip"
    )
    files = {
        path.relative_to(PROJECT_ROOT).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(paths)
    }
    return {
        "task_id": "CDH-I01-REWORK-002",
        "project_root": str(PROJECT_ROOT),
        "file_count": len(files),
        "files": files,
    }


def compare(before_path: Path) -> dict[str, object]:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = collect()
    before_files = before["files"]
    after_files = after["files"]
    missing = sorted(set(before_files) - set(after_files))
    added = sorted(set(after_files) - set(before_files))
    mismatched = sorted(
        name for name in set(before_files) & set(after_files) if before_files[name] != after_files[name]
    )
    return {
        "task_id": "CDH-I01-REWORK-002",
        "before_manifest": before_path.as_posix(),
        "before_file_count": len(before_files),
        "after_file_count": len(after_files),
        "missing": missing,
        "added": added,
        "mismatched": mismatched,
        "pass": not missing and not added and not mismatched,
        "after": after,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    result = compare(args.compare) if args.compare else collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"files", "after"}}, ensure_ascii=False))
    return 0 if result.get("pass", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
