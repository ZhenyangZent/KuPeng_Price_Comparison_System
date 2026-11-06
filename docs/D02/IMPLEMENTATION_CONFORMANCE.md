# CDH A02–D02 Receipt Contract v1 實作對照

- `receipt_version` 固定為 `CDH-D01-RECEIPT-1`；`exchange_version` 固定為 `CDH-EXCHANGE-1`。
- `entries` 是 cutoff 時 `submission_*.json` 的有界完整清單，依檔名排序且不重複。
- 每筆含精確檔名、讀取 bytes 的 lowercase SHA-256、契約允許的 status 與 reason code。
- A 只有在目前 inbox 檔名與 SHA 同時匹配 `IMPORTED`／`DUPLICATE_NOOP` 時才可視為 processed。
- `QUARANTINED` 不是成功；`RETRY_NEEDED` 仍 pending。
- snapshot 的 SHA 是 `latest.json` 實際 bytes 的 SHA-256，發布順序固定為 snapshot 先、receipt 後。
- receipt 缺失、過大、格式錯誤、schema 未知或 snapshot 不一致時，A 必須顯示未知／尚未一致，不可捏造 pending=0。
- 本實作不升級 qualification，不授權來源，不修改 A 擁有的 submission。

凍結契約原文位於 D02 輸入包：`input/orchestrator_bundles/D02/extracted/CDH_AB_RECEIPT_CONTRACT_V1.md`。
