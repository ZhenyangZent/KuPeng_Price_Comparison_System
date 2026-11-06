# C10 資料生命週期

- mode 固定為 `EPHEMERAL_LOCAL_PREVIEW`。
- retention 必須明確選擇，且為 1–7 日。
- `delete_at` 必須是 UTC `Z`、晚於評估時間、不得超過七日，亦不得晚於 collection／retention／display 任一權利期限。
- raw payload policy 固定為 `NO_RAW_PAYLOAD_PERSISTENCE`。
- derived preview policy 固定為 `EPHEMERAL_LOCAL_ONLY`。
- 使用者必須確認刪除；未確認即拒絕。
- C10 decision 不回傳來源 ID、evidence ID 或原始資料內容，避免 preview response 洩漏。

以上僅是本輪 synthetic dry-run policy，不代表正式資料保存機制或 production retention policy。
