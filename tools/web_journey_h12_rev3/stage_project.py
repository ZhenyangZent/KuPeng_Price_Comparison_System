from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools" / "web_journey_h12_rev2" / "stage_project.py"


def main() -> None:
    spec = importlib.util.spec_from_file_location("h12_rev2_stage", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load the hash-gated A16 staging implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.H12 = ROOT / "review" / "H12_REV3"
    module.RUNTIME = module.H12 / "runtime"
    module.PROJECT = module.RUNTIME / "project"
    module.main()


if __name__ == "__main__":
    main()
