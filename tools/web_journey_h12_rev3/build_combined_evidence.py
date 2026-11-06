from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H12 = ROOT / "review" / "H12_REV3"
REV2 = ROOT / "review" / "releases" / "CDH_H_R12_004_REVIEW.zip"
REV2_SHA = "df490f54ff4315e2c4171248464040e02ce2eef58265d1e5c3f88e4854294b80"
PREFIX = "CDH_H_R12_004_REVIEW/"
REV2_EVIDENCE = "evidence/ACTUAL_H12_REV2_BROWSER_HTTP.json"
OUT = H12 / "evidence" / "COMBINED_GATE_EVIDENCE.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if sha256(REV2) != REV2_SHA:
        raise RuntimeError("H12 REV2 ZIP identity mismatch")
    with zipfile.ZipFile(REV2) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("H12 REV2 CRC failure")
        manifest_bytes = archive.read(PREFIX + "MANIFEST.json")
        manifest = json.loads(manifest_bytes)
        declared = {item["path"]: item for item in manifest["payloads"]}
        item = declared[REV2_EVIDENCE]
        evidence_bytes = archive.read(PREFIX + REV2_EVIDENCE)
        if len(evidence_bytes) != item["bytes"] or hashlib.sha256(evidence_bytes).hexdigest() != item["sha256"]:
            raise RuntimeError("H12 REV2 browser evidence payload mismatch")
        rev2 = json.loads(evidence_bytes)
    rev3_path = H12 / "evidence" / "TARGETED_AFFILIATE_GATE.json"
    rev3 = json.loads(rev3_path.read_text(encoding="utf-8"))
    prior_failed = [name for name, passed in rev2["gates"].items() if not passed]
    prior_passed = [name for name, passed in rev2["gates"].items() if passed]
    combined = {
        "task_id": "CDH-H12-LOCAL-MVP-FIRST-USE-001",
        "revision": "REV3",
        "status": "PASS_SCOPED_COMPOSITE_EVIDENCE" if rev3["status"] == "PASS" and prior_failed == ["first_use_controls_and_classification"] else "FAIL",
        "single_run_full_17_gate_claimed": False,
        "h12_rev2": {
            "filename": REV2.name,
            "sha256": REV2_SHA,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "browser_test_exit_code": rev2["browser_test_exit_code"],
            "chrome_process_exit_code": rev2["chrome_process_exit_code"],
            "preserved_status": rev2["status"],
            "passed_gate_count": len(prior_passed),
            "gate_count": len(rev2["gates"]),
            "failed_gates": prior_failed,
            "evidence_payload_path": REV2_EVIDENCE,
            "evidence_payload_sha256": item["sha256"],
        },
        "h12_rev3_targeted": {
            "scope": rev3["scope"],
            "status": rev3["status"],
            "targeted_browser_test_exit_code": rev3["targeted_browser_test_exit_code"],
            "chrome_process_exit_code": rev3["chrome_process_exit_code"],
            "targeted_gate_pass_count": rev3["targeted_gate_pass_count"],
            "targeted_gate_count": rev3["targeted_gate_count"],
            "load_sample_count": rev3["load_sample_count"],
            "actionable_during_load_count": rev3["actionable_during_load_count"],
            "final_cta_count": rev3["final_state"]["cta_count"],
            "final_cta_disabled": rev3["final_state"]["cta_disabled"],
            "final_affiliate_anchor_count": rev3["final_state"]["affiliate_anchor_count"],
            "external_request_count": rev3["external_request_count"],
        },
        "composite_product_gate_pass_count": len(prior_passed) + (1 if rev3["status"] == "PASS" else 0),
        "composite_product_gate_count": len(rev2["gates"]),
        "interpretation": "Sixteen H12 REV2 gates remain hash-bound historical evidence; REV3 newly supplies only the previously failed first-use controls/classification condition.",
    }
    OUT.write_text(json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": combined["status"], "prior": f'{len(prior_passed)}/{len(rev2["gates"])}', "targeted": rev3["status"], "composite": f'{combined["composite_product_gate_pass_count"]}/{combined["composite_product_gate_count"]}'}))
    raise SystemExit(0 if combined["status"] == "PASS_SCOPED_COMPOSITE_EVIDENCE" else 1)


if __name__ == "__main__":
    main()
