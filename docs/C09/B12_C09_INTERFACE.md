# B12 ↔ C09 staging provenance gate

介面版本固定為：

- request：`CDH-B12-C09-GATE-REQUEST-1`
- staged record proposal：`CDH-B12-STAGING-RECORD-PROPOSAL-1`
- decision：`CDH-C09-PROVENANCE-DECISION-1`

B12 應將正規化但尚未寫入的 staging row 與 provenance evidence 一起送入 `verify_request`，或將 UTF-8 JSON bytes 送入 `verify_json`。缺少 C09 verifier、載入失敗、schema 不符、非 `ALLOW_SYNTHETIC_PREFLIGHT` 或任何 exception 都必須視為 `DENY`。

```python
try:
    from research.import_provenance_c09 import verify_request
    decision = verify_request(candidate, now=evaluation_time)
except Exception:
    decision = {"decision": "DENY"}

if decision.get("decision") != "ALLOW_SYNTHETIC_PREFLIGHT":
    reject_candidate()
else:
    render_ephemeral_preview_only()
```

通過只代表合成資料可在本機暫存 preview 中測試。`canonical_write_authorized`、`b11_mutation_authorized`、`runtime_authorized` 永遠為 `false`；不得寫入 B11 snapshot、正式 user DB、歷史資料庫或公開頁面。

目前尚未收到精確 B12 release，因此 adapter 實際重播為 `NOT_RUN_INPUT_UNAVAILABLE`。本文件是 versioned interface proposal，不修改 B 工作線檔案。
