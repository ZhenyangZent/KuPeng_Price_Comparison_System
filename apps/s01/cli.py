"""Command-line entry point for the S01 offline clue adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .clue_adapter import ClueInputError, import_csv_file, import_pasted_text, import_text_file, write_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize explicit local user clues without fetching any URL")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, help="UTF-8 CSV explicitly selected by the user")
    source.add_argument("--text-file", type=Path, help="UTF-8 local text file; each non-empty line is one clue")
    source.add_argument("--text", help="Text explicitly pasted by the user")
    parser.add_argument("--output", required=True, type=Path, help="New JSON output path (must not exist)")
    parser.add_argument("--observed-at", help="Timezone-aware ISO-8601 observation time")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.csv is not None:
            result = import_csv_file(args.csv, observed_at=args.observed_at)
        elif args.text_file is not None:
            result = import_text_file(args.text_file, observed_at=args.observed_at)
        else:
            result = import_pasted_text(args.text, observed_at=args.observed_at)
        write_result(result, args.output)
    except (ClueInputError, OSError) as exc:
        print(json.dumps({"status": "REJECTED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": "CLUES_WRITTEN", "output": str(args.output), "count": len(result["clues"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
