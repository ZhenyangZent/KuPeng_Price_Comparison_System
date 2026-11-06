from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
H03 = PROJECT / "review" / "H03"
EVIDENCE = H03 / "evidence"
OUTPUT = EVIDENCE / "H03_VERIFICATION.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


def main() -> None:
    baselines = load(H03 / "BASELINE_READBACK.json")
    before = load(H03 / "runtime" / "A07_B08_CONTRACT_RESULTS.json")
    after = load(H03 / "runtime" / "A08_B09_CONTRACT_RESULTS.json")
    browser = load(EVIDENCE / "BROWSER_JOURNEY_A08_B09.json")
    har = load(EVIDENCE / "NETWORK_HAR_A08_B09.json")
    expected_hashes = {
        "A07": "390499b3c99b2d3b551530be357f2810d6299db7c8cbd8ab182cf8ca2e19db90",
        "B08": "a6d5ffb65860fcb33504baefd3c5288c1c75aac0494af248bb3e4c5624cd69bd",
        "A08": "5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d",
        "B09": "10f7ae283108b460ce533b52b75ba1698218632b38d5b58fbda8e643b9234bab",
    }
    package_gates = {}
    for label, expected in expected_hashes.items():
        item = baselines["baselines"][label]
        package_gates[label] = {
            "sha256": item["sha256"],
            "sha_match": item["sha256"] == expected,
            "crc": item["archive"]["crc"],
            "manifest_pass": item["manifest"]["pass"],
            "manifest_mismatch": item["manifest"]["mismatch"],
            "unsafe_paths": item["archive"]["unsafe_paths"],
        }
    screenshots = []
    for item in browser["results"]:
        path = PROJECT / Path(item["screenshot"])
        width, height = png_dimensions(path)
        screenshots.append({"case": item["case"], "path": item["screenshot"], "sha256": sha256(path), "width": width, "height": height, "pass": item["pass"]})
    a08_fixture = H03 / "baselines" / "A08" / "CDH_A08_001_REVIEW" / "apps" / "price-web" / "frontend" / "src" / "fixtures.ts"
    malformed = "T0${i+8}:00:00Z" in a08_fixture.read_text(encoding="utf-8")
    result = {
        "task_id": "CDH-H03-A07-B08-INTEGRATION-JOURNEY-001",
        "authority": "AUTHORIZED_SYNTHETIC_OFFLINE_ONLY",
        "package_gates": package_gates,
        "before_a07_b08": {"counts": before["counts"], "central_reproduction_match": before["central_reproduction_match"], "product_integration_gate": before["product_integration_gate"]},
        "after_a08_b09": {"counts": after["counts"], "expected_outcome_match": after["expected_outcome_match"], "product_integration_gate": after["product_integration_gate"]},
        "browser": {"journey_count": len(browser["results"]), "all_pass": browser["all_journeys_pass"], "external_request_count": browser["network"]["external_request_count"], "har_external_request_count": har["external_request_count"], "screenshots": screenshots},
        "known_defects": [
            {
                "id": "H03-A08-SYNTHETIC-TIMESTAMP-001",
                "scope": "A08 built-in TEST_ONLY fixture",
                "observed": malformed,
                "detail": "Third generated history timestamp uses T010 when i=2 and renders as 時間格式無效.",
                "product_b09_contract_impact": False,
                "modified_by_h": False,
            }
        ],
        "gates": {
            "all_package_integrity": all(item["sha_match"] and item["crc"] == "PASS" and item["manifest_pass"] and item["manifest_mismatch"] == 0 and item["unsafe_paths"] == 0 for item in package_gates.values()),
            "before_reproduction": before["counts"] == {"total": 9, "pass": 6, "fail": 3} and before["central_reproduction_match"],
            "after_contract": after["counts"] == {"total": 9, "pass": 9, "fail": 0} and after["expected_outcome_match"] and after["product_integration_gate"] == "PASS",
            "browser_journeys": len(browser["results"]) == 5 and browser["all_journeys_pass"],
            "network_isolation": browser["network"]["external_request_count"] == 0 and har["external_request_count"] == 0,
            "known_defect_recorded": malformed,
        },
    }
    result["overall_verification"] = "PASS_WITH_KNOWN_A08_FIXTURE_DEFECT" if all(result["gates"].values()) else "FAIL"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall_verification": result["overall_verification"], "gates": result["gates"]}, ensure_ascii=False))
    if result["overall_verification"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
