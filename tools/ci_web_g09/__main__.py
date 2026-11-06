from __future__ import annotations
import argparse, json
from pathlib import Path
from .runner import run


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path.cwd()); parser.add_argument("--run-id", required=True); parser.add_argument("--receipt-ack", type=Path, required=True); args = parser.parse_args(); releases = args.root / "review" / "releases"
    report, code = run(root=args.root, run_id=args.run_id, a11_zip=releases / "CDH_A_R09_001_REVIEW.zip", b11_zip=releases / "CDH_B_R07_001_REVIEW.zip", receipt_ack=args.receipt_ack); print(json.dumps(report["summary"], sort_keys=True)); return code


if __name__ == "__main__": raise SystemExit(main())
