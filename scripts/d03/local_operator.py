from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CODE_ROOT / "apps/d01"))
sys.path.insert(0, str(CODE_ROOT / "apps/d03"))

from cdh_d03.operator import CONTRACT, DATA_SCOPE, DATABASE_KIND, SOURCE_STATUS, LocalOperator  # noqa: E402


class UsageError(ValueError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def parser() -> argparse.ArgumentParser:
    result = JsonArgumentParser(description="CDH D03 explicit offline local sync operator")
    result.add_argument("command", choices=("status", "preflight", "dry-run", "execute", "verify"))
    result.add_argument("--project-root", required=True, type=Path)
    result.add_argument("--json", action="store_true", help="emit compact JSON (stdout is JSON in either mode)")
    result.add_argument("--plan-id")
    result.add_argument("--operator-confirmed", action="store_true")
    return result


def fallback(command: str, code: str, detail: str) -> dict[str, object]:
    return {
        "contract": CONTRACT,
        "command": command,
        "result": "BLOCKED",
        "source_status": SOURCE_STATUS,
        "data_scope": DATA_SCOPE,
        "plan_id": None,
        "database_kind": DATABASE_KIND,
        "dry_run": command == "dry-run",
        "counts": {"scanned": 0, "imported": 0, "duplicate": 0, "quarantined": 0, "pending": 0},
        "receipt": {"state": "UNKNOWN", "sha256": None},
        "snapshot": {"state": "UNKNOWN", "sha256": None},
        "backup": {"state": "NOT_REQUIRED", "path": None, "sha256": None},
        "errors": [{"code": code, "detail": detail}],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def main(
    argv: list[str] | None = None,
    *,
    canonical_root: Path | None = None,
    code_root: Path | None = None,
    isolated_test: bool = False,
) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    command = raw[0] if raw and not raw[0].startswith("-") else "invalid"
    compact = "--json" in raw
    try:
        args = parser().parse_args(raw)
        expected_root = (canonical_root or CODE_ROOT).resolve()
        supplied_root = args.project_root.resolve()
        if supplied_root != expected_root:
            raise UsageError("--project-root must equal the unique installed project root")
        if args.command != "execute" and (args.plan_id is not None or args.operator_confirmed):
            raise UsageError("--plan-id and --operator-confirmed are valid only for execute")
        operator = LocalOperator(
            code_root=(code_root or CODE_ROOT),
            project_root=supplied_root,
            isolated_test=isolated_test,
        )
        if args.command == "status":
            output = operator.status()
        elif args.command == "preflight":
            output = operator.preflight()
        elif args.command == "dry-run":
            output = operator.dry_run()
        elif args.command == "execute":
            output = operator.execute(plan_id=args.plan_id, operator_confirmed=args.operator_confirmed)
        elif args.command == "verify":
            output = operator.verify()
        else:  # pragma: no cover - argparse choices enforce this
            raise AssertionError(args.command)
    except UsageError as exc:
        output = fallback(command, "CLI_USAGE_ERROR", str(exc))
    except Exception as exc:
        output = fallback(command, "OPERATOR_INITIALIZATION_FAILED", f"{type(exc).__name__}: {exc}")
        output["result"] = "FAILED"
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":") if compact else None, indent=None if compact else 2))
    return 0 if output["result"] in {"READY", "NEEDS_OPERATOR_CONFIRMATION", "EXECUTED", "DRY_RUN", "NO_CHANGES"} else 3 if output["result"] == "FAILED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
