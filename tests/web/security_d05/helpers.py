from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlencode


TARGET_BASE = Path("target_inputs") if Path("target_inputs/review/releases/CDH_A06_001_REVIEW.zip").is_file() else Path(".")
RELEASES = (TARGET_BASE / "review" / "releases").resolve()


def workspace() -> Path:
    root = Path("review/D05_WEB/001/test_tmp") / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root.resolve()


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def request(app, path: str, query: dict[str, str] | None = None) -> tuple[int, dict[str, object], dict[str, str]]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": urlencode(query or {})}, start_response))
    return int(str(captured["status"]).split()[0]), json.loads(body), captured["headers"]
