from __future__ import annotations

import argparse
import json
from wsgiref.simple_server import make_server

from .api import PreviewStatusApp
from .cli import add_preview_arguments, build_from_args
from .preview import StrictIngressError


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="B14 loopback-only strict preview server")
    add_preview_arguments(value)
    value.add_argument("--host", default="127.0.0.1")
    value.add_argument("--port", type=int, default=8774)
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
    except StrictIngressError as exc:
        print(json.dumps({"status": "ERROR", "code": exc.code, "input_sha256": exc.input_sha256}, sort_keys=True))
        return 2
    if args.check:
        print(json.dumps({"status": "READY", "bind_host": args.host, "record_count": preview["input"]["record_count"], "database_write_count": 0}, sort_keys=True))
        return 0
    with make_server(args.host, args.port, PreviewStatusApp(preview)) as server:
        server.serve_forever()
    return 0
