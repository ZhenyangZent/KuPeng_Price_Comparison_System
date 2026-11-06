from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit import audit_tree, audit_zip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline CDH web artifact security audit")
    parser.add_argument("kind", choices=("tree", "zip"))
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--allowed-root", type=Path)
    parser.add_argument("--owner", choices=("A", "B", "F"), required=True)
    parser.add_argument(
        "--sentinel",
        action="append",
        default=[],
        help="Synthetic marker to search for; never pass a real secret.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    sentinels = tuple(value.encode("utf-8") for value in args.sentinel)
    if args.kind == "tree":
        if args.allowed_root is None:
            parser.error("tree audit requires --allowed-root")
        result = audit_tree(
            args.target,
            allowed_root=args.allowed_root,
            sentinels=sentinels,
            owner=args.owner,
        )
    else:
        result = audit_zip(args.target, sentinels=sentinels, owner=args.owner)
    payload = json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        root = Path.cwd().resolve()
        if output != root and root not in output.parents:
            raise ValueError("OUTPUT_OUTSIDE_PROJECT_ROOT")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
