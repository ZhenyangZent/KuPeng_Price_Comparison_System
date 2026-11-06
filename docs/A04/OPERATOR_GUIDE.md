# A04 Windows 每日本機管理操作指引

## 安全邊界

- 本介面只處理使用者明確輸入的 `USER_ENTERED`／`USER_FILE` 本機資料。
- `SOURCE_BLOCKED` 會常駐顯示；手動觀測價不是成交價，也不是網路優惠搜尋結果。
- `NT$0`、WOW、首購、運費／庫存／券／資格 `UNKNOWN` 都不代表免費或可購買。
- 程式不連線酷澎、不讀 Firefox、不讀寫 Registry、不發真通知，也不進行購物行為。

## 每日流程

1. 在「本機資料（手動）」輸入商品名稱、觀測價、UTC 時間及可選的 SKU／賣家／備註；或選擇自己的 CSV／JSON。
2. 保存後狀態是「等待本地同步」。這不表示已匯入，也不表示價格或資格已驗證。
3. 按「Preflight 安全檢查」。若 D02/D03 身分、SQLite 完整性、磁碟、writer lock、來源種類或回執不安全，流程會停止並顯示原因。
4. Preflight 通過後按「查看 Dry-run」。核對新增、重複、隔離、待處理計數、逐檔預覽、plan ID、失效時間與備份要求。
5. 只有未過期且仍綁定相同狀態的 plan 才會啟用 Execute。按下後仍會出現明確確認對話框。
6. D03 完成 execute 後，A04 自動執行 Verify，重新讀取 receipt、snapshot 與歷史。
7. 歷史列會分成「使用者新觀測」「已匯入」「重播無新增」「隔離拒收」「待審查／等待重試」。缺少有效 receipt 時不會顯示零筆成功。

## 中止與恢復

- 執行中按「取消目前操作」會終止 D03 子程序；舊 plan 不會自動執行。
- 關閉視窗時，若仍有 D03 子程序，A04 會先要求取消。
- timeout、非零 exit、無效 JSON、契約／來源權限不符或錯誤欄位不完整都會 Fail Closed；請修正原因後從 Preflight 重來。
- `PLAN_EXPIRED`：重新 Preflight 與 Dry-run。
- `PLAN_ALREADY_CONSUMED`：不要重播 execute；執行 Verify 後重新建立新 plan。
- `SINGLE_WRITER_BUSY`：等另一個本地同步結束，再從 Preflight 重試。
- `SOURCE_KIND_NOT_USER_PROVIDED`：移除或修正非 `USER_ENTERED`／`USER_FILE` 的輸入；不能用 GUI 提升來源權限。

## D04 歷史報表

A04 只讀固定提案位置 `data/exchange/reports/d04/latest.json`。檔案不存在時顯示「歷史報表尚未啟用」；契約或 `source_status` 不符時拒絕載入。A04 不會建立或修改 D04 報表。

