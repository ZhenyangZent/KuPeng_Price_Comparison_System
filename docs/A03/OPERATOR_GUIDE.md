# A03 Windows 操作指引

## 安全邊界

A03 僅保存使用者明確輸入或由檔案選擇器選取的資料。來源狀態維持 `SOURCE_BLOCKED`。價格觀測不是成交價，`NT$0`、未知運費、未知庫存、未知優惠券或未知會員資格都不能視為可購買優惠。

## 啟動與手動輸入

1. 在專案根目錄執行 `apps\a01\launch_a01.ps1`。
2. 開啟「本機資料（手動）」。
3. 輸入商品名稱、整數 TWD 價格與帶時區 UTC 時間；URL、商品 ID、SKU/規格與備註可留空。
4. 按「保存 USER_ENTERED（等待同步）」。畫面必須明確回報已建立或 `DUPLICATE_NOOP`。
5. 切到「追蹤與歷史」，確認來源為 `USER_ENTERED`、核實狀態為 `UNVERIFIED`，同步狀態為等待本地同步。

資料會寫成新的 `submission_<uuid>.json`。同 UUID 不覆蓋，寫入採暫存檔、flush、fsync 與原子建立。

## 匯入 CSV / JSON

按「選擇本機 CSV／JSON 匯入」，只會讀取所選檔案。CSV 必填 `product_title`、`displayed_price_twd`、`observed_at_utc`；JSON 為包含相同欄位的物件陣列。每列獨立驗證，錯誤列不阻止其他合法列，但總結會列出錯誤。完全相同檔案重播不會建立重複觀測。

## D03 同步流程

- `WAITING_FOR_D03`：同步元件不存在，所有同步操作停用；手動觀測仍可保存。
- `AVAILABLE_NOT_CHECKED`：已偵測 D03，但尚未執行狀態檢查；執行鍵仍停用。
- 依序按「讀取狀態」→「Preflight 安全檢查」→「查看 Dry-run」。
- 只有回覆通過固定契約驗證且 dry-run 取得 plan ID，才可點「確認後開始本地同步」。
- 最後一步仍會顯示明確對話框；只有使用者按「是」才傳入 `--operator-confirmed`。

任何逾時、非零返回碼、多餘 stdout、錯誤 JSON、命令不符、來源權限升級或結構不符都會失敗關閉；GUI 不顯示已匯入。

## 疑難排解

- `本地同步元件尚未完成`：等待 D03 獨立交付，不要直接操作正式 SQLite。
- `SOURCE_BLOCKED`：這是正確安全狀態，不代表程式故障。
- `SYNCING`／`UNKNOWN`：Receipt/Snapshot 尚未一致或無法驗證；重新讀取前不要假設完成。
- 需要重跑測試時，將 TEMP/TMP 指向 `experiments/A03/test_tmp`，避免測試資料落到專案外。
