from __future__ import annotations

import argparse
from pathlib import Path

from .runner import run


def main() -> int:
    parser = argparse.ArgumentParser(description="CDH G03 reproducible offline web CI")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    _, code = run(args.root, args.run_id)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
