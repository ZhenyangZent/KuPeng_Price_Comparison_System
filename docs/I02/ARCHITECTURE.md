# I02 合成資料同步預覽架構

`CDH-I02-LOCAL-SYNC-PREVIEW-001` 只把 A02 Windows 介面接到凍結的 D02 本地同步公開契約。它不是正式同步入口，也不增加任何資料來源權限。

## 邊界

- UI：`apps/a01/a01_app/gui.py` 既有「離線測試與設定」頁中的獨立 I02 面板。
- 適配器：`apps/a01/a01_app/i02_preview.py`；只接受專案下 `experiments/I02/<child>` 工作區。
- 唯讀相依：`apps/d01/cdh_d01.sync.run_sync`、`SyncPaths`、`database.connect/migrate`。載入時核對模組來源與 `CDH-D01-RECEIPT-1`、`CDH-EXCHANGE-1`、`SOURCE_BLOCKED`。
- 狀態解析：沿用 A02 `receipt_status()`；I02 只讀同一隔離工作區的 inbox、snapshot 與 receipt。

## 執行流程

1. 使用者按下 I02 面板操作鍵。
2. UI 立即鎖定三個 I02 操作鍵，工作交給 Qt worker thread；重複觸發回傳拒絕。
3. 適配器確認工作區在 `experiments/I02/**`，初始化隔離 SQLite，建立固定 UUID 的合成輸入。
4. dry-run 呼叫 D02 `run_sync(..., dry_run=True)`，顯示 `DRY_RUN`，不發布回執且不宣稱 `READY`。
5. 隔離寫入模式由 D02 發布 snapshot/receipt，再由 A02 回執契約解析並顯示 imported/pending/quarantined/retry。
6. 任一缺少相依、版本錯誤、執行中斷或驗證錯誤均顯示失敗／未知，絕不沿用成功計數。

## 安全性語意

- 固定合成價格包含 `NT$0`，但資料庫仍保存 `qualification_state=UNVERIFIED`、`shipping_status=UNKNOWN`、`shipping_fee_twd=null`。
- UI 永久顯示 `SYNTHETIC ONLY`、未知運費不等於免運、零元不代表可購買、不連線酷澎、不發送真實通知、不執行購物。
- P2 回執狀態陣列已在 A02 解析邊界改成受控 `ReceiptError`，UI 顯示 `UNKNOWN`，不再讓 worker 遭未處理 `TypeError`。
- 沒有 scheduler、背景常駐服務、任意 shell、使用者任意路徑或網路命令。

