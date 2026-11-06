# S01 clue 介面提案（未授權跨線整合）

STATUS: `PROPOSAL_ONLY`

CONTRACT_ID: `cdh-user-provided-clue-v1`

本文件只描述 S01 的本機輸出，不授權 C01/D01/D02/D03 或任何通知工作線讀取、匯入或轉換。

## Envelope

- `schema`: 固定 `cdh-user-provided-clue-v1`
- `adapter_version`: semantic version
- `generated_at`: UTC ISO-8601
- `input`: source type、basename label、SHA-256、bytes、record count
- `guardrails`: network/url fetch/C01 event/notification counters，全部為 0
- `clues`: bounded array，最多 1000 筆

## Clue invariants

- 來源只允許 `USER_FILE`／`USER_ENTERED`。
- `source_status=LOCAL_USER_INPUT_ONLY` 只表示本機處理權限。
- `automated_source_status` 必須為 `SOURCE_BLOCKED`。
- `upstream_permission_status` 必須為 `NOT_PROVEN`。
- `qualification` 的 12 個欄位必須全為 `UNKNOWN`。
- `notification_eligible`、`c01_event_created` 必須為 `false`。
- `links_fetched` 必須為 `0`。

## 未來整合 gate

任何 consumer 必須先取得新的跨線 authority，驗證 schema/version、input hash、clue identity、URL、時間與全 UNKNOWN invariant。不得用本提案把 clue 直接建成 quote、price observation、decision 或 notification event。
