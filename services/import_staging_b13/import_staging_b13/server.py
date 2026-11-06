from __future__ import annotations

import argparse
import json
from wsgiref.simple_server import make_server

from .api import PreviewStatusApp
from .cli import add_preview_arguments, build_from_args
from .preview import PreviewError


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="B13 loopback-only preview status server")
    add_preview_arguments(value)
    value.add_argument("--host", default="127.0.0.1")
    value.add_argument("--port", type=int, default=8773)
    value.add_argument("--check", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.host != "127.0.0.1":
        parser().error("host must be 127.0.0.1")
    if not 1 <= args.port <= 65535:
        parser().error("port outside allowed range")
    try:
        preview = build_from_args(args)
    except PreviewError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2
    if args.check:
        print(json.dumps({"status": "READY", "bind_host": args.host, "record_count": preview["input"]["record_count"], "database_write_count": 0}, sort_keys=True))
        return 0
    app = PreviewStatusApp(preview)
    with make_server(args.host, args.port, app) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
