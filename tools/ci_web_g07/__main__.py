from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import run


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path.cwd()); parser.add_argument("--run-id", required=True)
    parser.add_argument("--b11-zip", type=Path, required=True); parser.add_argument("--b11-sha", required=True)
    parser.add_argument("--f06-zip", type=Path, required=True); parser.add_argument("--f06-sha", required=True)
    parser.add_argument("--a10-candidate", type=Path, required=True); parser.add_argument("--receipt-ack", type=Path, required=True)
    parser.add_argument("--a10-sha"); parser.add_argument("--a10-lock-sha")
    args = parser.parse_args(); report, code = run(root=args.root, run_id=args.run_id, b11_zip=args.b11_zip, b11_sha=args.b11_sha, f06_zip=args.f06_zip, f06_sha=args.f06_sha, a10_candidate=args.a10_candidate, receipt_ack=args.receipt_ack, a10_sha=args.a10_sha, a10_lock_sha=args.a10_lock_sha)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True)); return code


if __name__ == "__main__": raise SystemExit(main())
