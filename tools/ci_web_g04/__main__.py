from __future__ import annotations

import argparse
from pathlib import Path

from .runner import A07_SHA, B08_SHA, run


def main() -> int:
    parser = argparse.ArgumentParser(description="CDH G04 immutable A/B release preflight")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--frontend-zip", type=Path, default=Path("review/releases/CDH_A07_001_REVIEW.zip"))
    parser.add_argument("--frontend-sha", default=A07_SHA)
    parser.add_argument("--backend-zip", type=Path, default=Path("review/releases/CDH_B08_001_REVIEW.zip"))
    parser.add_argument("--backend-sha", default=B08_SHA)
    parser.add_argument("--profile", choices=("baseline-defects", "canonical-fixed"), default="baseline-defects")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    frontend = args.frontend_zip if args.frontend_zip.is_absolute() else root / args.frontend_zip
    backend = args.backend_zip if args.backend_zip.is_absolute() else root / args.backend_zip
    _, code = run(root=root, run_id=args.run_id, frontend_zip=frontend, frontend_sha=args.frontend_sha, backend_zip=backend, backend_sha=args.backend_sha, profile=args.profile, include_headless=args.headless)
    return code


if __name__ == "__main__": raise SystemExit(main())
