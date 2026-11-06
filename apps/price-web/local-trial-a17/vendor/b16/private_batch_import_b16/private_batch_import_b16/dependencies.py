from __future__ import annotations

import sys
from pathlib import Path


B15_SERVICE_ROOT = Path(__file__).resolve().parents[2] / "private_observation_b15"
if str(B15_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(B15_SERVICE_ROOT))

