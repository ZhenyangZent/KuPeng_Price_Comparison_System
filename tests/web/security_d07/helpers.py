from __future__ import annotations

from pathlib import Path


TARGET_BASE = Path("target_inputs") if Path("target_inputs/review/releases/CDH_A08_001_REVIEW.zip").is_file() else Path(".")
RELEASES = (TARGET_BASE / "review" / "releases").resolve()
A08 = RELEASES / "CDH_A08_001_REVIEW.zip"
B09_002 = RELEASES / "CDH_B09_002_REVIEW.zip"
A08_SHA = "5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d"
B09_002_SHA = "35539f8d3434540c660ff51613e636c443ffc06b237806bc53f32db1e78e62e3"
