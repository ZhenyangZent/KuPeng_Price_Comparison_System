from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from tools.web_security_d10.gate import run_gate


TARGET_BASE = Path("target_inputs") if Path("target_inputs/review/releases/CDH_A_R08_001_REVIEW.zip").is_file() else Path(".")
RELEASES = (TARGET_BASE / "review" / "releases").resolve()


@lru_cache(maxsize=1)
def result():
    return run_gate(RELEASES)
