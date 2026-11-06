from __future__ import annotations

import json
from pathlib import Path

from tools.ci_web_g06.audit import sha256_file


REQUIRED_EVIDENCE = (
    "network.har", "dom_search.json", "dom_detail.json", "screenshot_search.png",
    "screenshot_detail.png", "browser_console.json", "api_request_log.json",
)


def evaluate(*, candidate: Path, receipt_ack: Path, explicit_sha256: str | None, explicit_lock_sha256: str | None) -> dict:
    result = {"status": "NOT_RUN_INPUT_UNAVAILABLE", "candidate_path": str(candidate), "candidate_exists": candidate.is_file(), "candidate_observed_sha256": None, "central_ack_match": False, "explicit_sha256": explicit_sha256, "explicit_lock_sha256": explicit_lock_sha256, "required_evidence": list(REQUIRED_EVIDENCE), "browser_executed": False}
    if candidate.is_file(): result["candidate_observed_sha256"] = sha256_file(candidate)
    if not receipt_ack.is_file():
        result["reason"] = "CENTRAL_RECEIPT_ACK_UNAVAILABLE"; return result
    ack = json.loads(receipt_ack.read_text(encoding="utf-8")); items = ack.get("items", ack.get("uploaded_files", []))
    accepted = [item for item in items if item.get("role") == "A" and item.get("filename") == candidate.name and item.get("sha256") == result["candidate_observed_sha256"]]
    result["central_ack_match"] = len(accepted) == 1
    if not result["central_ack_match"]:
        result["reason"] = "A10_NOT_CENTRALLY_ACKNOWLEDGED"; return result
    if explicit_sha256 != result["candidate_observed_sha256"]:
        result.update(status="NOT_RUN_IDENTITY_UNAVAILABLE", reason="EXPLICIT_A10_SHA_MISSING_OR_MISMATCH"); return result
    if not explicit_lock_sha256:
        result.update(status="NOT_RUN_DEPENDENCY_UNAVAILABLE", reason="EXPLICIT_A10_LOCK_SHA_REQUIRED"); return result
    result.update(status="READY_FOR_EXACT_BROWSER_EXECUTION", reason=None)
    return result
