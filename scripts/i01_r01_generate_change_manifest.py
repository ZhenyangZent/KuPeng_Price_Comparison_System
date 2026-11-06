from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "review/I01/R01/evidence/before/I01_R01_BASELINE.json"
OUTPUT = ROOT / "reports/I01/R01/CHANGE_MANIFEST.csv"
SCOPES = (ROOT / "src/cdh_integration", ROOT / "tests/i01", ROOT / "fixtures/i01")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    before = {item["path"]: item for item in baseline["i01_baseline_files"]}
    after_paths = sorted(
        path
        for scope in SCOPES
        for path in scope.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
    )
    before = {
        name: item
        for name, item in before.items()
        if "__pycache__" not in Path(name).parts and Path(name).suffix not in {".pyc", ".pyo"}
    }
    after = {
        path.relative_to(ROOT).as_posix(): {"sha256": digest(path), "size": path.stat().st_size}
        for path in after_paths
    }
    rows = []
    for name in sorted(set(before) | set(after)):
        if name not in before:
            status = "ADDED"
        elif name not in after:
            status = "REMOVED"
        elif before[name]["sha256"] != after[name]["sha256"]:
            status = "MODIFIED"
        else:
            status = "UNCHANGED"
        if status != "UNCHANGED":
            rows.append(
                {
                    "path": name,
                    "status": status,
                    "before_sha256": before.get(name, {}).get("sha256", ""),
                    "after_sha256": after.get(name, {}).get("sha256", ""),
                    "before_bytes": before.get(name, {}).get("size", ""),
                    "after_bytes": after.get(name, {}).get("size", ""),
                }
            )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("path", "status", "before_sha256", "after_sha256", "before_bytes", "after_bytes"),
        )
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"output": OUTPUT.relative_to(ROOT).as_posix(), "changed_path_count": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
