from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import run


def main() -> int:
    parser = argparse.ArgumentParser(description="CDH G06 exact A10/B11 or expected-fail A09/B10 verifier")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--frontend-zip", type=Path, required=True)
    parser.add_argument("--frontend-sha", required=True)
    parser.add_argument("--backend-zip", type=Path, required=True)
    parser.add_argument("--backend-sha", required=True)
    parser.add_argument("--profile", choices=("a09-b10-expected-fail", "a10-b11-exact"), required=True)
    args = parser.parse_args()
    report, code = run(root=args.root, run_id=args.run_id, frontend_zip=args.frontend_zip,
                       frontend_sha=args.frontend_sha, backend_zip=args.backend_zip,
                       backend_sha=args.backend_sha, profile=args.profile)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
