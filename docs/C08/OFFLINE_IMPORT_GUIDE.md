# C08 離線匯入准入指南

匯入 record 使用 `CDH-C08-B10-IMPORT-1`，內含原封不動的 B10 Search 或 Detail envelope、選定 `series_key`、預期精確 identity、C07 provenance sidecar、撤銷狀態及固定 pending review gate。

## 最小流程

1. 使用者日後自行提供合法授權、已脫敏資料時，先保留來源文件 SHA-256，不放入秘密原文或帳號識別。
2. `wire_envelope` 不得自行增加商品級 `schema_version`，也不得把 Detail history 塞進 product。
3. 核對 product/SKU/seller/condition/package、scope evidence、eligibility profile、valid until 與 source permission。
4. 依五項獨立 rights 判斷是否可保存／展示歷史；affiliate 權永遠獨立。
5. dedupe key 由 identity、series、時間、source、coupon、文件 SHA 與 data version 組成。完全相同為 `DUPLICATE_NOOP`；同 key 不同 record 為 `DEDUPE_CONFLICT`。
6. 證據撤銷或到期後，停止新展示、歷史准入與通知；不得自動恢復。

執行 fixture：`python -m research.coupon_b10_mapping_c08.cli research/coupon_b10_mapping_c08/B10_MAPPING_FIXTURES.json --case DETAIL_DUAL_HISTORY_ALLOWED_TEST_ONLY --now 2026-11-05T04:00:00Z`。

目前 B10 wire 只授權非私人合成資料。任何 user-provided record 都會回 `B10_REAL_IMPORT_NOT_SUPPORTED`，直到 B 工作線另行提供經中央核准的真實資料 authority。
