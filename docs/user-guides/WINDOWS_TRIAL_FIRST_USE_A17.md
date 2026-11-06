# Coupang Deal Hunter Windows 本機試用版

這個 A17 試用版把正式驗收過的網站、B11 合成展示服務、B15/B16 私人價格服務與必要的雜湊基準整合在專案內。日常啟動不需要自行尋找八份歷史 ZIP，也不會自動連線酷澎。

## 系統需求

- Windows 10 或 Windows 11。
- Python 3.11 以上。啟動器依序檢查專案 `.venv`、`py -3`、PATH 的 `python` 與標準使用者安裝位置。
- 試用版必須留在本專案根目錄內；不要把 `apps\price-web\local-trial-a17` 單獨搬到其他位置。

## 三個入口

在專案最上層使用：

1. 雙擊 `Start-CDH-Trial.cmd` 啟動。
2. 雙擊 `Status-CDH-Trial.cmd` 查看狀態。
3. 雙擊 `Stop-CDH-Trial.cmd` 安全停止。

啟動後請在瀏覽器開啟：

`http://127.0.0.1:4174/?mode=synthetic&contract=v4`

命令列及自動驗證可加 `-MachineReadable`，會輸出 JSON 並保留真實退出碼，不會 `pause`。

## 可以試用的功能

- 搜尋離線合成示範商品與價格歷史。
- 手動預覽並明確確認一筆私人價格。
- 預覽並確認 UTF-8 CSV／JSON 批次匯入（上限 1 MiB、500 筆）。
- 以名稱、商品 ID 或 SKU 搜尋已保存的私人商品。
- 查看券前、自報券後、符合證據時才存在的平台確認券後歷史。

## 資料分類

- `SYNTHETIC DEMO`：離線示範，不是真實酷澎價格。
- `PRIVATE USER-REPORTED`：只存在本機的使用者自報資料。
- `PLATFORM CONFIRMED`：只有完整資格與優惠券證據通過時才顯示；自報價格不會升格。

正式推薦／分潤按鈕維持停用。

## 私人資料與日誌

- 私人歷史：`data\A17_private_history`
- 啟動收據與控制狀態：`data\A17_trial\state`
- 執行期檔案：`data\A17_trial\runtime`
- 日誌：`logs\A17`

這些位置都在唯一專案根目錄內。A17 REVIEW ZIP 不包含任何上述執行期私人資料。

## 自動預檢與錯誤

啟動前會逐檔核對 `apps\price-web\local-trial-a17\A17_RUNTIME_MANIFEST.json`。缺件、大小或 SHA-256 不符時會 fail closed，不會啟動部分版本。

- `PYTHON_NOT_FOUND`／`PYTHON_TOO_OLD`：安裝 Python 3.11 以上或建立專案 `.venv`。
- `A17_RUNTIME_FILE_MISSING`／`A17_RUNTIME_FILE_SHA256_MISMATCH`：試用包不完整或遭修改，請恢復正式 A17 交件。
- `PORT_IN_USE`：`127.0.0.1:4174` 已占用；啟動器不會終止未知程序。
- `STALE_RECEIPT_MANUAL_REVIEW`／`PROCESS_IDENTITY_MISMATCH_MANUAL_REVIEW`：保存狀態與程序不一致；工具不會強制殺除未知 PID。

試用版不安裝服務、不修改 Registry、不讀取 `.env`、不啟動 Firefox、不連線酷澎、不公開部署，也不執行分潤點擊或購物交易。
