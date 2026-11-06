# D02 本機同步操作手冊

## 安全邊界

`CDH-D02-LOCAL-SYNC-RECEIPTS-001` 只處理專案內的本機檔案。它不連線到外部網站、不讀 Firefox Profile、不修改 Registry、不建立 Windows Scheduled Task 或 service，也不執行通知、領券、購物車、下單或付款。商品 URL 只保存為文字，永不擷取。

固定資料流：

`data/exchange/inbox/submission_<canonical-uuid>.json` → `data/d01/observations.sqlite3` → `data/exchange/snapshots/latest.json` → `data/exchange/receipts/latest.json`

程式不接受自訂 DB、inbox、snapshot 或 receipt 路徑；所有路徑固定在唯一專案根目錄。inbox 檔案不會被刪除或改寫。

## 明確手動執行

先從專案根目錄執行唯讀 dry-run：

```powershell
scripts\d02\run_local_sync.ps1 --dry-run --pretty
```

或不依賴 PowerShell execution policy：

```bat
scripts\d02\run_local_sync.cmd --dry-run --pretty
```

確認 JSON 結果後，使用者可明確執行一次正式同步：

```powershell
scripts\d02\run_local_sync.ps1 --pretty
```

本次交件與測試不執行上列正式命令，因此不會修改現有使用者資料庫或發布 runtime receipt。

## 結果語意

- `IMPORTED`：檔案已新增至 append-only ledger。
- `DUPLICATE_NOOP`：相同檔名與 SHA 已處理，沒有新增重複 observation。
- `QUARANTINED`：內容或身分衝突，屬錯誤而非成功匯入。
- `RETRY_NEEDED`：檔案在讀取期間變動，保持 pending，下一輪重試。

所有使用者價格一律維持 `UNVERIFIED`。未知會員資格、運費、coupon、庫存及費用仍是 `UNKNOWN`；整體來源狀態固定為 `SOURCE_BLOCKED`。

## 中斷恢復

同步使用 OS 單寫入者鎖。SQLite 匯入與每檔 outcome 同一 transaction；snapshot 以 tmp＋fsync＋atomic replace 發布，receipt 只在 snapshot 成功後發布。若在 DB commit 後或 snapshot 後中斷，重新手動執行相同命令即可；精確 replay 不會新增 observation，也不會無界增加 attempt／quarantine 紀錄。

若 receipt 與 snapshot SHA 不一致，A 端應顯示「正在同步／尚未一致」，不得顯示全部完成。

## 容量與保留

- inbox 目錄最多掃描 5,000 個直接子項；單次 receipt 最多 1,000 個 submission 檔。
- 單一 submission 最大 1,048,576 bytes；receipt 最大 2 MiB。
- 只保留最近 32 個 versioned snapshot 與 32 個 versioned receipt；`latest.json` 不計入此上限。
- 容量超限、symlink/reparse point、路徑錯誤或 single-writer contention 都 fail closed，不發布新的成功 receipt。
