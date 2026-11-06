# CDH-LOCAL-MANUAL-SYNC-1 JSON 實作說明

每個回覆固定包含：

`contract`、`command`、`result`、`source_status`、`data_scope`、`plan_id`、`database_kind`、`dry_run`、`counts`、`receipt`、`snapshot`、`backup`、`errors`、`generated_at`。

固定值：

- `contract = CDH-LOCAL-MANUAL-SYNC-1`
- `source_status = SOURCE_BLOCKED`
- `data_scope = USER_PROVIDED_LOCAL_ONLY`
- `database_kind = USER_LOCAL`

`counts` 的五個欄位固定為 `scanned/imported/duplicate/quarantined/pending`。回執只有檔名與 SHA 都匹配目前 inbox，且 status 是 `IMPORTED` 或 `DUPLICATE_NOOP`，才視為已處理。

Plan 綁定 DB 的 SQLite 一致性邏輯 SHA、DB 檔案 SHA、inbox 檔名／SHA／來源類型、snapshot SHA、receipt SHA、D02 release SHA 與受保護模組 SHA。Plan 內容被改動、超過 10 分鐘、已使用或任一綁定狀態變化時，`execute` 回覆 `BLOCKED`。

`errors` 只包含有限的 `code/detail`，不含 Cookie、token、帳號、訂單、完整 HTML 或商品內容。Plan 與 operator log 只保存檔名、SHA、來源類型、計數與錯誤碼。
