from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from cdh_d04.history import (  # noqa: E402
    CONTRACT,
    HistoryError,
    export_history,
    quality_report_markdown,
    write_versioned_export,
)


def _aware(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CDH D04 read-only local price history export")
    parser.add_argument("--database", type=Path, required=True, help="manually selected D01 SQLite database")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of", type=_aware, required=True)
    parser.add_argument("--generated-at", type=_aware)
    args = parser.parse_args(argv)
    try:
        report = export_history(
            args.database,
            as_of=args.as_of,
            generated_at=args.generated_at or datetime.now(timezone.utc),
        )
        output, digest = write_versioned_export(report, args.output_dir)
        quality = args.output_dir / f"quality_{digest[:12]}.md"
        quality.write_text(quality_report_markdown(report), encoding="utf-8", newline="\n")
        result = {
            "contract": CONTRACT,
            "result": "EXPORTED",
            "database_mode": "READ_ONLY",
            "output": str(output.resolve()),
            "output_sha256": digest,
            "quality_report": str(quality.resolve()),
            "series_count": report["quality"]["exported_series_count"],
            "source_status": "SOURCE_BLOCKED",
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (HistoryError, OSError) as exc:
        print(
            json.dumps(
                {
                    "contract": CONTRACT,
                    "result": "FAILED",
                    "database_mode": "READ_ONLY",
                    "error": str(exc),
                    "source_status": "SOURCE_BLOCKED",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
