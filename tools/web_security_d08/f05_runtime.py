from __future__ import annotations

import importlib
import sys
from pathlib import Path

from tools.web_security_d06.targets import unique_member_name


def run_f05_parser(f05_zip: str | Path, cases: list[dict[str, object]]) -> list[dict[str, object]]:
    target = Path(f05_zip).resolve()
    member = unique_member_name(target, "services/affiliate_coupon_gate_v5/affiliate_coupon_gate_v5/__init__.py")
    internal = member[: -len("affiliate_coupon_gate_v5/__init__.py")].rstrip("/")
    import_path = str(target) + "/" + internal
    for name in tuple(sys.modules):
        if name == "affiliate_coupon_gate_v5" or name.startswith("affiliate_coupon_gate_v5."):
            del sys.modules[name]
    sys.path[:] = [item for item in sys.path if "affiliate_coupon_gate_v5" not in item.replace("\\", "/")]
    sys.path.insert(0, import_path)
    importlib.invalidate_caches()
    parser = importlib.import_module("affiliate_coupon_gate_v5.parser")
    results: list[dict[str, object]] = []
    for case in cases:
        try:
            value = parser.parse_coupon_snapshot(case["payload"])
            results.append({"name": case["name"], "success": True, "value": repr(value)})
        except Exception as exc:  # exact upstream error type is loaded from immutable archive
            results.append({"name": case["name"], "success": False, "code": getattr(exc, "code", type(exc).__name__), "message": str(exc)})
    return results
