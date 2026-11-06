from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import make_server

from .api import PriceQueryApp
from .repository import ReadonlyPriceRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-only CDH price query API")
    parser.add_argument("--database-copy", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    repository = ReadonlyPriceRepository(
        args.database_copy,
        allowed_root=args.fixture_root,
        clock=lambda: datetime.now(timezone.utc),
    )
    app = PriceQueryApp(repository)
    with make_server(args.host, args.port, app) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
