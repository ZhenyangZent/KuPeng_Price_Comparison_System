from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .c09_adapter import load_verified_c09_verifier
from .provenance import DefaultDenyVerifier, ProvenanceContractError
from .staging import ImportStagingError, dry_run, load_records, safe_input_path


def _timestamp(value: str) -> datetime:
    if not value.endswith("Z"):
        raise argparse.ArgumentTypeError("timestamp must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid UTC timestamp") from exc
    return parsed


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="B12 immutable CSV/JSON import preflight")
    value.add_argument("--input", type=Path, required=True)
    value.add_argument("--allowed-root", type=Path, required=True)
    value.add_argument("--format", choices=("auto", "csv", "json"), default="auto")
    value.add_argument("--as-of", type=_timestamp, required=True)
    value.add_argument("--c09-request-bundle", type=Path)
    value.add_argument("--c09-release", type=Path)
    value.add_argument("--require-all-accepted", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        records, input_sha256 = load_records(args.input, allowed_root=args.allowed_root, input_format=args.format)
        verifier = DefaultDenyVerifier()
        if (args.c09_request_bundle is None) != (args.c09_release is None):
            raise ProvenanceContractError("C09 request bundle and release must be supplied together")
        if args.c09_request_bundle is not None and args.c09_release is not None:
            bundle_path = safe_input_path(args.c09_request_bundle, args.allowed_root)
            release_path = safe_input_path(args.c09_release, args.allowed_root)
            project_root = Path(__file__).resolve().parents[3]
            verifier = load_verified_c09_verifier(bundle_path, expected_input_sha256=input_sha256, c09_release=release_path, project_root=project_root)
        report = dry_run(records, input_sha256=input_sha256, as_of=args.as_of, verifier=verifier)
    except (ImportStagingError, ProvenanceContractError) as exc:
        print(json.dumps({"schema_version": "CDH-B12-CLI-ERROR-1", "status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.require_all_accepted and report["counts"]["ACCEPTED_FOR_STAGING_PREVIEW"] != report["record_count"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
