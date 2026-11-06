# A02 R01 回執相容性決策

任務：`CDH-A02-RECEIPT-COMPAT-REWORK-002`

此修正不變更 `CDH-EXCHANGE-1` 或 `CDH-D01-RECEIPT-1`，只落實中央 Orchestrator 對既有欄位的窄幅解釋：

- `IMPORTED`：`reason_code` 必須是 `null`。
- `DUPLICATE_NOOP`：`reason_code` 只能是 `null` 或精確字串 `IDENTICAL_REPLAY`。
- `DUPLICATE_NOOP` 的檔名與 SHA-256 仍必須吻合目前 inbox 檔案，才能算已處理。
- 任意其他非空理由（例如 `SUSPICIOUS`）仍會使回執失效。
- `QUARANTINED` 仍是錯誤，`RETRY_NEEDED` 仍是待處理。

回執只證明檔案處理狀態，不會升級商品資格，也不會把未知價格、運費、庫存、優惠券、帳戶資格或必要費用轉成有效優惠或零元。

