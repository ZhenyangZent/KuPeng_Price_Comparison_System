#!/usr/bin/env python3
"""Apply exact H13 REV2 / E23 REV3 central receipts to E-owned handoff state."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/HANDOFF"
ARCHIVE = ROOT / "review/90_UPLOADED_ARCHIVE/20261107_H13_REV2_E23_REV3_ACK"
ACKS = {
    "CDH_H_R13_002_REVIEW.zip": "2ba4ef61975e9350cb10cc6aa5551d16b2615a92c8886ea86b8207e1750f6682",
    "CDH_E_R13_003_REVIEW.zip": "392a6dface7057b3ebe6203fba78c9f8d5a7b53c09a7693327d293721296134f",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup(path: Path) -> None:
    target = DOCS / "versions" / (path.stem + "_PRE_H13_REV2_E23_REV3_20261107" + path.suffix)
    if not target.exists():
        shutil.copy2(path, target)


def main() -> None:
    assert ROOT.name == "酷澎比價系統"
    for name, expected in ACKS.items():
        for folder in (ROOT / "review/releases", ARCHIVE):
            if sha(folder / name) != expected:
                raise RuntimeError(f"exact ACK mismatch: {name}")
    ledger = DOCS / "RELEASE_LEDGER.csv"
    backup(ledger)
    with ledger.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        assert fields is not None
        rows = list(reader)
    by_name = {r["filename"]: r for r in rows}
    if "CDH_E_R13_002_REVIEW.zip" in by_name:
        by_name["CDH_E_R13_002_REVIEW.zip"]["publication_status"] = "RECEIVED_NOT_PUBLISHED"
    additions = [
        ("CDH_H_R13_002_REVIEW.zip", "CDH-H13-LOCAL-TRIAL-FIRST-USE-001",
         "PASS_SCOPED_COMPOSITE_EVIDENCE", "BLOCKED_FOR_UPLOAD_PENDING_DEEP_REVIEW"),
        ("CDH_E_R13_003_REVIEW.zip", "CDH-E23-GITHUB-REPOSITORY-CONSOLIDATION-20261106",
         "PARTIAL_PASS_SCOPED", "RECEIVED_NOT_PUBLISHED"),
    ]
    for name, task, decision, publication in additions:
        if name in by_name:
            if by_name[name]["sha256"] != ACKS[name]:
                raise RuntimeError(f"ledger collision: {name}")
            by_name[name].update(central_decision=decision, publication_status=publication)
            continue
        row = dict(filename=name, task_id=task, version=name.removesuffix(".zip"),
                   sha256=ACKS[name], central_decision=decision,
                   local_release_path="review/releases/" + name,
                   github_download_url="NOT_PUBLISHED", publication_status=publication)
        rows.append(row)
        by_name[name] = row
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    ledger.write_bytes(buf.getvalue().encode("utf-8"))
    state_path = DOCS / "CURRENT_STATE.json"
    backup(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["h13"] = {
        "task_id": "CDH-H13-LOCAL-TRIAL-FIRST-USE-001",
        "filename": "CDH_H_R13_002_REVIEW.zip",
        "sha256": ACKS["CDH_H_R13_002_REVIEW.zip"],
        "central_decision": "PASS_SCOPED_COMPOSITE_EVIDENCE",
        "central_received_ack": True,
        "product_pass": True,
        "evidence_scope": "REV1 failure preserved plus targeted REV2 rerun; not a single full E2E rerun",
        "rev1_failure_preserved": True,
    }
    state["e23_revision_3"] = {
        "filename": "CDH_E_R13_003_REVIEW.zip",
        "sha256": ACKS["CDH_E_R13_003_REVIEW.zip"],
        "central_decision": "PARTIAL_PASS_SCOPED",
        "central_received_ack": True,
    }
    state["historical_release_audit_baseline_count"] = 140
    state["historical_release_incremental_snapshot_count"] = 1
    state["historical_release_risk_triage_count"] = 134
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    master = DOCS / "MASTER_HANDOFF.md"
    backup(master)
    content = master.read_text(encoding="utf-8")
    if "## 52. H13 REV2／E23 REV3" not in content:
        content += (
            "\n## 52. H13 REV2／E23 REV3 中央裁決與增量安全審查（2026-11-07 Asia/Taipei）\n\n"
            "- 中央精確 RECEIVED ACK：H13 REV2 `CDH_H_R13_002_REVIEW.zip` SHA `2ba4ef61975e9350cb10cc6aa5551d16b2615a92c8886ea86b8207e1750f6682`；E23 REV3 `CDH_E_R13_003_REVIEW.zip` SHA `392a6dface7057b3ebe6203fba78c9f8d5a7b53c09a7693327d293721296134f`。經 release／queue 完整 SHA、CRC、Manifest 核對，兩份 queue 副本精確歸檔至 `review/90_UPLOADED_ARCHIVE/20261107_H13_REV2_E23_REV3_ACK/`；原件不變。\n"
            "- H13 最新中央裁決為 `PASS_SCOPED_COMPOSITE_EVIDENCE`，以 REV1 舊 FAIL 與 REV2 定點補驗組成，不宣稱單次完整 E2E PASS。H13 REV1 原始 FAIL、瀏覽器退出碼與 REV2 補驗前失敗均保留。E23 REV3 裁決為 `PARTIAL_PASS_SCOPED`，不是完整 GitHub 封存或產品發布授權。\n"
            "- 原 140 份審查結果凍結於 `reports/E23/release_audit/BASELINE_140.json` 與 `batch_00.json`–`batch_06.json`；新增交件另存 `incremental_snapshot_000.json` 與 `incremental_000_batch_00.json`，舊 checkpoint 不覆寫。134 份待審原件已完成 metadata-only 風險分組；原件尚無新增公開核准。\n"
            "- 公開 GitHub 歷史 prerelease 目前仍只有六份已驗證資產。候選 PR #1 維持 Draft、未合併；`main` 文件入口不是完整 A17 Runtime。新增公開資產須通過實際內容、權限、Manifest、CRC 與遠端 digest gate。\n"
        )
        master.write_text(content, encoding="utf-8")
    readme = ROOT / "README.md"
    old = "H13 REV1 已由中央確認為有效失敗報告，搜尋測試工具待修訂，不能宣稱首次試用產品流程全線通過。"
    new = "H13 REV2 的中央裁決為 `PASS_SCOPED_COMPOSITE_EVIDENCE`；REV1 原始 FAIL 與 REV2 定點補驗前失敗均保留，不宣稱單次完整 E2E PASS。"
    text = readme.read_text(encoding="utf-8")
    if old in text:
        readme.write_text(text.replace(old, new), encoding="utf-8")
    print(json.dumps({"ack_verified": len(ACKS), "ledger_rows": len(rows),
                      "h13_decision": state["h13"]["central_decision"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
