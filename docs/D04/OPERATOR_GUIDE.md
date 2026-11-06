# D04 本地歷史唯讀操作指南

## 目的

D04 將使用者手動輸入或檔案匯入的 D01/D02 observation 匯出為 `CDH-LOCAL-HISTORY-1`。它不連線酷澎、不讀 Firefox、不讀寫 Registry、不發通知、不操作任何購物流程。

## 命令

必須由人或後續 GUI 明確指定 SQLite 與輸出目錄：

```powershell
python apps/d04/history_cli.py `
  --database C:\path\selected\observations.sqlite3 `
  --output-dir C:\path\history-output `
  --as-of 2026-11-04T12:00:00+08:00
```

成功 exit code `0`，stdout 為單一 JSON 並含 `result=EXPORTED`、輸出路徑及 SHA-256。輸入、schema 或輸出錯誤 exit code `2`，stdout 為 `result=FAILED`。

CLI 沒有正式 DB 預設路徑，因此不會因為單純啟動就讀取使用者資料。D04 不建立 migration，也不提供資料庫寫入或 restore 功能。

## 解讀限制

- `is_comparable=true` 只代表同一完整 D01 identity 的 displayed item-price exploratory comparison。
- `historical_low_twd` 是合格完成日的中位數最低點，不是結帳總價，也不是通知授權。
- `SOURCE_BLOCKED`、`UNVERIFIED`、shipping／stock／coupon／eligibility UNKNOWN 必須原樣呈現。
- `verified_checkout_low_claim_allowed` 和 `true_drop_claim_allowed` 固定為 `false`。
- 詳細 schema 與 stale 規則見 `CONTRACT_PROPOSAL.md`。

## 隔離範例

本交件的 sample、SQLite、效能報告都在 `experiments/D04/001/`，完全是合成工作區，不是使用者正式資料。
