#!/usr/bin/env python3
"""Copy a fixed E23 public allowlist into the isolated Git candidate only."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "review/E23_GITHUB_CANDIDATE/repo"
BASE = [
    "README.md", "docs/00_START_HERE.md", "docs/HANDOFF/MASTER_HANDOFF.md",
    "docs/HANDOFF/CURRENT_STATE.json", "docs/HANDOFF/RELEASE_LEDGER.csv",
    "reports/E23/H13_REV2_E23_REV3_ACK_RESULT.json",
    "reports/E23/release_audit/BASELINE_140.json",
    "reports/E23/release_audit/incremental_snapshot_000.json",
    "reports/E23/release_audit/incremental_000_batch_00.json",
    "reports/E23/release_audit/RISK_TRIAGE_SUMMARY.json",
    "reports/E23/release_audit/RISK_TRIAGE_REPORT.md",
    "reports/E23/E23_REPLAY.md",
] + [f"reports/E23/release_audit/triage_batch_{i:02d}.json" for i in range(7)]
BRANCH_ONLY = [
    "scripts/orchestrator_handoff/e23_release_audit.py",
    "scripts/orchestrator_handoff/e23_risk_triage.py",
    "scripts/orchestrator_handoff/e23_apply_central_decision.py",
    "scripts/orchestrator_handoff/e23_stage_public.py",
    "scripts/orchestrator_handoff/e23_reindex_public.py",
    "scripts/orchestrator_handoff/e23_verify_staged.py",
    "scripts/orchestrator_handoff/flat_queue.py",
    "scripts/orchestrator_handoff/handoff_batch.py",
    "tests/handoff/test_e23_release_audit.py",
    "tests/handoff/test_e23_risk_triage.py",
]
TOKEN = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----|sk-[A-Za-z0-9]{30,})")
EMAIL = re.compile(rb"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
WIN_USER = re.compile(rb"C:[\\/]Users[\\/][^\\/\s\"']+", re.I)
PASSWORD = re.compile(rb"(?:password|passwd|client_secret|api_key|access_token)\s*[:=]\s*[\"'][^\"']{8,}[\"']", re.I)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("main", "branch"), required=True)
    mode = p.parse_args().mode
    assert ROOT.name == "酷澎比價系統" and (DEST / ".git").is_dir()
    paths = BASE + (BRANCH_ONLY if mode == "branch" else [])
    for name in paths:
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"missing or symlink public source: {name}")
        data = source.read_bytes()
        if name in {"docs/HANDOFF/CURRENT_STATE.json", "docs/HANDOFF/MASTER_HANDOFF.md"}:
            data = WIN_USER.sub(b"LOCAL_USER_HOME", data)
        if name == "docs/HANDOFF/MASTER_HANDOFF.md":
            data = data.replace(b"\r\n", b"\n")
            data = b"\n".join(line.rstrip(b" \t") for line in data.split(b"\n"))
        if TOKEN.search(data) or EMAIL.search(data) or WIN_USER.search(data) or PASSWORD.search(data) or b"\x00" in data:
            raise RuntimeError(f"possible private data in public candidate: {name}")
        dest = DEST / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    print(f"MODE={mode} COPIED={len(paths)}")


if __name__ == "__main__":
    main()
