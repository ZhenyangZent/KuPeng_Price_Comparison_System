from __future__ import annotations

import argparse
from pathlib import Path

from .gui import run_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Coupang Deal Hunter A01 offline Windows preview")
    parser.add_argument("--screenshot", type=Path, help="capture a synthetic-data-safe UI screenshot and exit")
    parser.add_argument("--screenshot-tab", type=int, default=0, help="zero-based tab index used with --screenshot")
    parser.add_argument("--exit-after-ms", type=int, help="test-only automatic close")
    args = parser.parse_args()
    return run_app(screenshot=args.screenshot, screenshot_tab=args.screenshot_tab, exit_after_ms=args.exit_after_ms)


if __name__ == "__main__":
    raise SystemExit(main())
