from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import make_server

from .api import BatchImportApp
from .baselines import verify_baselines
from .store import BatchObservationStore


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="B16 private-local CSV/JSON batch import service")
    value.add_argument("--host", default="127.0.0.1")
    value.add_argument("--port", type=int, default=8785)
    value.add_argument("--allowed-origin", action="append", default=[])
    value.add_argument("--check", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.host != "127.0.0.1":
        parser().error("host must be 127.0.0.1")
    if not 1 <= args.port <= 65535:
        parser().error("port outside allowed range")
    if any(not (item.startswith("http://127.0.0.1:") or item.startswith("http://localhost:")) for item in args.allowed_origin):
        parser().error("allowed origins must be explicit loopback HTTP origins")
    project_root = Path(__file__).resolve().parents[3]
    baselines = verify_baselines(project_root / "review" / "releases")
    store = BatchObservationStore(
        project_root / "data" / "private_user_observations_b15",
        allowed_project_root=project_root,
    )
    if args.check:
        print(json.dumps({
            "status": "READY",
            "bind_host": args.host,
            "database_exists": store.database.exists(),
            "baselines": baselines,
            "batch_api_schema": "CDH-B16-PRIVATE-BATCH-API-1",
        }, sort_keys=True))
        return 0
    app = BatchImportApp(
        store,
        baselines=baselines,
        clock=lambda: datetime.now(timezone.utc),
        allowed_origins=tuple(args.allowed_origin),
    )
    with make_server(args.host, args.port, app) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

