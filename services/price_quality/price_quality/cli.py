from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .model import QualityError, QualityReadModel


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline authorized-copy price quality report")
    parser.add_argument("--database-copy", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--allowed-root", type=Path, required=True)
    parser.add_argument("--as-of", required=True, help="timezone-aware RFC3339 timestamp")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        as_of = datetime.fromisoformat(arguments.as_of.replace("Z", "+00:00"))
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError
    except ValueError:
        parser.error("--as-of must be a timezone-aware RFC3339 timestamp")
    try:
        model = QualityReadModel(
            arguments.database_copy,
            arguments.authorization,
            allowed_root=arguments.allowed_root,
            clock=lambda: as_of,
        )
        report = model.analyze(page=arguments.page, limit=arguments.limit)
    except QualityError as exc:
        parser.exit(2, f"quality read refused: {exc}\n")
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if arguments.output is None:
        print(payload, end="")
    else:
        output = arguments.output.absolute()
        allowed_root = arguments.allowed_root.absolute().resolve()
        if output.exists() and output.is_symlink():
            parser.exit(2, "refusing symlink output\n")
        if not output.parent.resolve().is_relative_to(allowed_root):
            parser.exit(2, "output must stay below allowed root\n")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
