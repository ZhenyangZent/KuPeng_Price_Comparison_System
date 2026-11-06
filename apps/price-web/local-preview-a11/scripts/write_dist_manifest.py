from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DIST = ROOT / "apps" / "price-web" / "frontend" / "dist"
MANIFEST = DIST / "A11_DIST_MANIFEST.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not (DIST / "index.html").is_file():
        raise SystemExit("frontend dist is missing; run npm build first")
    files = []
    for item in sorted(DIST.rglob("*")):
        if item.is_file() and item != MANIFEST:
            files.append({"path": item.relative_to(DIST).as_posix(), "size": item.stat().st_size, "sha256": sha256(item)})
    payload = {"schema_version": "CDH-A11-DIST-MANIFEST-1", "files": files}
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "manifest": str(MANIFEST), "file_count": len(files), "sha256": sha256(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
