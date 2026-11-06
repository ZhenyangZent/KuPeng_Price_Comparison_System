from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from tools.web_security_d06.targets import read_unique_member

from .temp_scope import scoped_temp


def run_a09_parser(a09_zip: str | Path, cases: list[dict[str, object]]) -> list[dict[str, object]]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("NODE_RUNTIME_NOT_AVAILABLE")
    runner = Path(__file__).with_name("a09_runner.mjs")
    with scoped_temp("a09") as root:
        source = root / "couponRuntimeSchema.ts"
        types = root / "couponTypes.ts"
        source.write_bytes(read_unique_member(a09_zip, "apps/price-web/frontend/src/couponRuntimeSchema.ts"))
        types.write_bytes(read_unique_member(a09_zip, "apps/price-web/frontend/src/couponTypes.ts"))
        environment = os.environ.copy()
        environment["TEMP"] = str(root)
        environment["TMP"] = str(root)
        result = subprocess.run(
            [node, "--no-warnings", str(runner), "--source", str(source), "--types", str(types)],
            input=json.dumps(cases, ensure_ascii=False), text=True, encoding="utf-8", errors="strict",
            capture_output=True, check=False, timeout=30, env=environment,
        )
        if result.returncode:
            raise RuntimeError(f"A09_NODE_RUNTIME_FAILURE:{result.returncode}:{result.stderr}")
        value = json.loads(result.stdout)
        if not isinstance(value, list):
            raise RuntimeError("A09_NODE_RUNTIME_OUTPUT_INVALID")
        return value
