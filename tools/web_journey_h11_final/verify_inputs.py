from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "web_journey_h11"))
import verify_inputs as shared  # noqa: E402


OUT = ROOT / "review" / "H11_FINAL" / "INPUT_READBACK.json"
INPUTS = {
    "A15_REV2": ("CDH_A_R12_002_REVIEW.zip", "be0becbaa384e1a633c5893b266dbbb03c449ca405ef1f0c07bb8dd53456634b", "SHA256_MANIFEST.json"),
    "B16_REV3": ("CDH_B_R12_003_REVIEW.zip", "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7", "REVIEW_MANIFEST.json"),
    "D13_REV3": ("CDH_D_R12_003_REVIEW.zip", "8aef750caa17c894159d13705f9962e4f6e856ef3ced1658ddb951523b241e54", "REVIEW_MANIFEST.json"),
}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    inputs = {label: shared.inspect(label, *value) for label, value in INPUTS.items()}
    result = {
        "task_id": "H11",
        "revision": "FINAL_OFFICIAL_LAUNCHER",
        "status": "PASS",
        "inputs": inputs,
        "b16_api_schema": inputs["B16_REV3"]["api_schema"],
        "b16_api_route_or_request_schema_change_count": inputs["B16_REV3"]["api_route_or_request_schema_change_count"],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
