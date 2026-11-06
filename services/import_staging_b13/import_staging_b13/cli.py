from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .preview import PreviewError, build_preview


def _timestamp(value: str) -> datetime:
    if not value.endswith("Z"):
        raise argparse.ArgumentTypeError("timestamp must use UTC Z form")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid UTC timestamp") from exc


def add_preview_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--b12-release", type=Path, required=True)
    parser.add_argument("--c09-release", type=Path, required=True)
    parser.add_argument("--b11-release", type=Path, required=True)
    parser.add_argument("--c09-request-bundle", type=Path)
    parser.add_argument("--as-of", type=_timestamp, required=True)


def build_from_args(args: argparse.Namespace) -> dict[str, object]:
    project_root = Path(__file__).resolve().parents[3]
    return build_preview(
        args.input,
        input_root=args.input_root,
        dependency_root=args.dependency_root,
        b12_release=args.b12_release,
        c09_release=args.c09_release,
        b11_release=args.b11_release,
        as_of=args.as_of,
        project_root=project_root,
        c09_request_bundle=args.c09_request_bundle,
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="B13 immutable import preview")
    add_preview_arguments(value)
    value.add_argument("--require-all-accepted", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        preview = build_from_args(args)
    except PreviewError as exc:
        print(json.dumps({"schema_version": "CDH-B13-CLI-ERROR-1", "status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(preview, ensure_ascii=False, indent=2, sort_keys=True))
    if args.require_all_accepted and preview["summary"]["ACCEPTED_FOR_STAGING_PREVIEW"] != preview["input"]["record_count"]:
        return 3
    return 0
