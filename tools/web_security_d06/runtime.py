from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .temp_scope import scoped_temp
from .targets import read_unique_member


def _node() -> str:
    value = shutil.which("node")
    if value is None:
        raise RuntimeError("NODE_RUNTIME_NOT_AVAILABLE")
    return value


def _run(command: list[str], payload: list[dict[str, object]], temp_root: Path) -> list[dict[str, object]]:
    environment = os.environ.copy()
    environment["TEMP"] = str(temp_root)
    environment["TMP"] = str(temp_root)
    result = subprocess.run(
        command,
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env=environment,
        encoding="utf-8",
        errors="strict",
    )
    if result.returncode:
        raise RuntimeError(f"NODE_RUNTIME_FAILURE:{result.returncode}:{result.stderr}")
    value = json.loads(result.stdout)
    if not isinstance(value, list):
        raise RuntimeError("NODE_RUNTIME_OUTPUT_INVALID")
    return value


def run_frontend_parser(frontend_zip: str | Path, cases: list[dict[str, object]]) -> list[dict[str, object]]:
    runner = Path(__file__).with_name("node_runtime_runner.mjs")
    with scoped_temp("parser") as root:
        runtime = root / "runtimeSchema.ts"
        types = root / "types.ts"
        runtime.write_bytes(read_unique_member(frontend_zip, "apps/price-web/frontend/src/runtimeSchema.ts"))
        types.write_bytes(read_unique_member(frontend_zip, "apps/price-web/frontend/src/types.ts"))
        return _run([
            _node(), "--no-warnings", str(runner), "--mode", "parser",
            "--source", str(runtime), "--types", str(types),
        ], cases, root)


def run_affiliate_policy(frontend_zip: str | Path, cases: list[dict[str, object]]) -> list[dict[str, object]]:
    runner = Path(__file__).with_name("node_runtime_runner.mjs")
    with scoped_temp("affiliate") as root:
        source = root / "affiliate.ts"
        source.write_bytes(read_unique_member(frontend_zip, "apps/price-web/frontend/src/affiliate.ts"))
        return _run([
            _node(), "--no-warnings", str(runner), "--mode", "affiliate", "--source", str(source),
        ], cases, root)
