from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "preview_server_a15.py"
SPEC = importlib.util.spec_from_file_location("cdh_a15_preview_server_exact", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load exact A15 preview server")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

MODULE.B16_SHA256 = "6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6"
MODULE.B16_SERVICES_PREFIX = "CDH_B_R12_002_REVIEW/services/"

for _name in dir(MODULE):
    if not _name.startswith("__"):
        globals()[_name] = getattr(MODULE, _name)


if __name__ == "__main__":
    raise SystemExit(MODULE.main())
