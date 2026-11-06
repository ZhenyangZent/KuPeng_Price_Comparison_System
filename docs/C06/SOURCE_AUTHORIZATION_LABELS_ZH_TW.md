# 已收錄商品／來源授權標籤與管理流程

在沒有新官方能力證據時，網站仍可對「已收錄資料的來源與限制」提供可理解、可稽核的標籤。這些標籤不表示酷澎全站覆蓋，也不授權分潤 CTA。

## 建議標籤

- `SYNTHETIC_DEMO`：純合成展示資料，不對應真實商品。
- `CONTRACT_FIXTURE_TEST_ONLY`：只用於跨線契約測試。
- `USER_AUTHORIZED_COPY`：使用者明確提供、只供本人使用的資料副本；需保留授權時間與來源證據。
- `USER_RECORDED_OBSERVATION`：使用者主動記錄的單次觀測；不代表完整市場價格。
- `OFFICIAL_SOURCE_CANDIDATE`：來源聲稱官方，但仍待 byte identity／市場／scope 人工複查。
- `OFFICIAL_SOURCE_VERIFIED`：來源文件已核對；只代表文件來源，不代表資料、帳號或 runtime 權利。
- `SOURCE_BLOCKED`：來源或權利證據不足，不得擷取、保存、展示或導購。

## 商品紀錄最小管理欄位

- `source_authorization_label`
- `source_evidence_id` 與 `source_document_sha256`
- `market`、`observed_at`、`product_id`、`variant_id`
- `price_basis` 與資料是否為原始觀測或衍生代表值
- `retention_right_state`、`display_right_state`、`correction_deletion_state`
- `affiliate_link_right_state`（必須與資料權分開）
- `expires_at`、`revoked_at`、`last_reviewed_at`

## 顯示文案

- 價格可用：`此價格為已收錄觀測，不代表酷澎全站或即時最低價。`
- 價格不可用：`目前沒有適用且可比的價格觀測。`
- 歷史有限：`僅顯示此頁已收錄的觀測；資料可能受時間、數量與來源限制。`
- 官方能力未授權：`目前未提供分潤導購連結。`

## 管理狀態轉移

新紀錄先進 `QUARANTINED`；完成 byte identity、來源、期限及權利核對後才可進 `REVIEWED`。任何證據到期、撤銷、hash 改變或 scope 不明，立即回到 `SOURCE_BLOCKED`。不得自動恢復或自動啟用 CTA。
