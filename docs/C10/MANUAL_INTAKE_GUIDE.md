# C10 人工來源 intake 指南

C10 在 C09 exact verifier 前新增明確的人工作業選項，並不擴大 C09 權限。使用者必須選擇來源類別、蒐集／歷史保存／本機展示／連結揭露四項權利、資料生命週期及隱私聲明。

支援的類別：

- `SYNTHETIC_PREFLIGHT`：唯一可能得到 `ALLOW_SYNTHETIC_PREFLIGHT` 的類別。
- `USER_MANUAL_ENTRY`：只記錄為 `EVIDENCE_REVIEW_REQUIRED / DENY`。
- `USER_FILE`：只記錄為 `EVIDENCE_REVIEW_REQUIRED / DENY`。
- `OFFICIAL_LICENSED_SOURCE`：沒有獨立 authority review 前一律 `DENY`。

允許的 synthetic 預覽必須選擇 collection、history retention、local display，不得選擇 link disclosure；raw payload 不保存，derived preview 只在本機暫存，1–7 日內刪除，且刪除時間不得晚於 C09 權利期限。

執行 fixture：

`python -m research.import_provenance_c10.cli research/import_provenance_c10/C10_INTAKE_FIXTURES.json --now 2026-11-05T06:00:00Z --fixture-case ALLOW_SYNTHETIC_MANUAL_INTAKE`
