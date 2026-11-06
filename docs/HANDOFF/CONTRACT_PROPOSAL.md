# CDH-HANDOFF-BATCH-1 跨線唯讀交件契約

STATUS: `IMPLEMENTED_UNDER_E01_AUTHORITY_PENDING_ORCHESTRATOR_REVIEW`

PRODUCERS: 各工作線只在 `review/releases` 保存自己的 `CDH_<ID>_REVIEW.zip`。

CONSUMER: E01 `handoff_batch.py` 只讀被明確列名的 releases；不掃描或修改其他工作線原始碼。

OUTPUT: `review/00_TO_UPLOAD/CDH_BATCH_<BATCHID>_REVIEW.zip`，只含 `BATCH_MANIFEST.json` 與 `packages/<原始 release ZIP>`。

MANIFEST: `schema`, `batch_id`, `original_releases_preserved`, `release_count`, `files[]`；每個 file record 含 `name`, `size_bytes`, `sha256`, `entries`, `uncompressed_bytes`, `crc`, `path_safety`, `sensitive_content_gate`。

ARCHIVE_GATE: 必須同時提供合法 batch 名稱、中央 Orchestrator 明確回報的 lowercase SHA-256 與 `--acknowledged`。封存只移動 outer batch，不移動或刪除 releases。

FAIL_CLOSED: 不安全 ZIP 路徑、Windows alias、symlink、CRC／解壓錯誤、敏感檔名、大小限制、碰撞、未確認或錯誤 hash 均不得建立／封存批次。

