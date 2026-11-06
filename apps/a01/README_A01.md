# Coupang Deal Hunter A03 Windows 本機手動價格管理

## A04 每日本機管理

版本 `0.5.0-a04-daily-local` 保留 A01/A02/I02/A03 功能，加入正式 D03 五步操作、plan 到期阻擋、逐檔 dry-run、備份／receipt／snapshot 狀態、自動 Verify、取消與異常恢復，以及唯讀 D04 報表狀態。完整使用方式請參閱 `docs/A04/OPERATOR_GUIDE.md`。

A03 延伸 A01/A02/I02 的離線 Windows GUI，讓使用者明確輸入或選取本機 CSV/JSON，累積 `USER_ENTERED`／`USER_FILE` 價格觀測。它不開啟商品網址、不連線酷澎、不讀 Firefox、不寫 Registry、不發通知，也不執行購物行為。

## Windows 啟動

執行環境固定於 `apps/a01/.venv`。交付 ZIP 不包含 `.venv`；依 `requirements.lock` 建立環境後，在專案根目錄執行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File apps\a01\launch_a01.ps1
```

## 四個頁籤

1. **首頁 / Source Health**：顯示 `SOURCE_BLOCKED`、Snapshot/Receipt 與待處理狀態；缺資料不會顯示假成功。
2. **本機資料（手動）**：輸入名稱、整數 TWD 價格、UTC 時間、可選 URL、SKU/規格與備註，或由檔案選擇器匯入 CSV/JSON。未確認的運費、庫存、券、帳號資格、必要費用固定為 `UNKNOWN`。
3. **追蹤與歷史**：合併顯示等待同步的 inbox 與唯讀 Snapshot，區分來源、同步與核實狀態。`NT$0` 只顯示為未核實觀測。
4. **離線測試與設定**：保留既有 I02 合成隔離預覽；不與手動資料混為真實商品資格。

## CSV / JSON

CSV 必填欄位：

```text
product_title,displayed_price_twd,observed_at_utc
```

可選欄位為 `url`、`product_id`、`variant_id`、`seller_id`、`sku`、`specification`、`notes`。JSON 接受物件陣列，欄位語意相同。檔案必須是 UTF-8、一般檔案且不超過 1 MiB；最多 10,000 列。公式字首、負數、浮點、NaN、Infinity、空白價格及不合法 UTC 會逐列拒絕。重播完全相同的列使用確定性 UUID，因此回報 `DUPLICATE_NOOP` 而不覆蓋既有檔案。

## 本地同步確認

A03 只呼叫固定入口：

```text
python scripts/d03/local_operator.py <status|preflight|dry-run|execute|verify> --project-root <root> --json
```

呼叫使用參數陣列與 `shell=False`，並驗證單一 JSON 回覆、契約、命令、結果、來源狀態、資料範圍與結構。`execute` 只有在 preflight 與 dry-run 成功、取得 plan ID，且使用者在確認對話框按下「是」後才會解鎖。GUI 從不直接寫 SQLite。D03 不存在時所有同步按鈕停用並顯示 `WAITING_FOR_D03`。

## 測試

```powershell
$env:TEMP = (Resolve-Path 'experiments/A03/test_tmp').Path
$env:TMP = $env:TEMP
$env:PYTHONPATH = (Resolve-Path 'apps/a01').Path
apps\a01\.venv\python.exe -m unittest discover -s tests/a03 -p 'test_*.py' -v
```

完整回歸與 Windows 實測結果見 `reports/A03/001/`；操作說明見 `docs/A03/OPERATOR_GUIDE.md`。
