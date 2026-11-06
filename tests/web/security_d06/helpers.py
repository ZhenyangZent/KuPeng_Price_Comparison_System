from __future__ import annotations

from pathlib import Path


TARGET_BASE = Path("target_inputs") if Path("target_inputs/review/releases/CDH_A07_001_REVIEW.zip").is_file() else Path(".")
RELEASES = (TARGET_BASE / "review" / "releases").resolve()
A07 = RELEASES / "CDH_A07_001_REVIEW.zip"
B08 = RELEASES / "CDH_B08_001_REVIEW.zip"
A08 = RELEASES / "CDH_A08_001_REVIEW.zip"
B09 = RELEASES / "CDH_B09_001_REVIEW.zip"
A07_SHA = "390499b3c99b2d3b551530be357f2810d6299db7c8cbd8ab182cf8ca2e19db90"
B08_SHA = "a6d5ffb65860fcb33504baefd3c5288c1c75aac0494af248bb3e4c5624cd69bd"
A08_SHA = "5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d"
B09_SHA = "10f7ae283108b460ce533b52b75ba1698218632b38d5b58fbda8e643b9234bab"
