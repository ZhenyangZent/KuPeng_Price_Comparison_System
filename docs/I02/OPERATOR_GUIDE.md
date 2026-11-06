# I02 Windows 操作指引

## 啟動

從唯一專案根目錄使用既有 A01 專用環境啟動：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File apps\a01\launch_a01.ps1
```

進入「離線測試與設定」，使用「合成資料同步預覽」面板。預設工作區是 `experiments/I02/synthetic_preview`，不會讀寫 `data/d01` 或 `data/exchange`。

## 三個操作

- `執行隔離寫入同步`：建立第一個固定合成商品並由凍結 D02 寫入隔離 SQLite、snapshot、receipt。
- `Dry-run 檢查（不發佈回執）`：驗證輸入但不發布新回執；畫面只顯示 `DRY_RUN`。
- `加入第二個固定合成商品`：只加入合成輸入，狀態先顯示 `PENDING`；需再次執行隔離同步才可得到新回執。

預期四循環為：第一次 `1/0`、相同資料重播 `1/0`、加入第二商品後同步 `2/0`、再次重播 `2/0`。

## 故障語意

- `FAILED`：runner／相依／路徑或寫入錯誤；不顯示成功計數。
- `SYNCING`：receipt 與 snapshot 尚未一致。
- `UNKNOWN`：receipt 損壞、版本不支援或內容無法驗證。
- `PENDING`：新增合成檔尚未同步，不能視為完成。

刪除或重建隔離工作區只適用於已確認的 `experiments/I02/**` 測試資料。本任務未授權操作正式使用者資料庫、Firefox、Registry、酷澎網站、真實通知或購物行為。

