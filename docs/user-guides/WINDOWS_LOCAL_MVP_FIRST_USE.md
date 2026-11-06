# Coupang Deal Hunter Windows 本機版：第一次使用

這個版本在你的 Windows 電腦上啟動本機網站，支援搜尋合成示範商品、手動記錄價格、CSV／JSON 批次匯入，以及重新開啟網站後查詢私人歷史。它不會自動連線酷澎、不會自動開啟瀏覽器，也不會修改 Registry 或安裝系統服務。

## 使用前準備

- Windows 10 或 Windows 11。
- Python 3.11 以上。啟動器依序使用專案內 `.venv`、Windows `py -3`、PATH 中的 `python`。
- 專案必須在 `review\releases` 保留下列 8 份正式 release。這同時包含網站的直接依賴，以及 B15／B16 實際啟動時會驗證的間接依賴；啟動器會逐一核對完整 SHA-256，不要求使用者自行猜測缺件：

  - `CDH_A_R08_001_REVIEW.zip` — `0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd`
  - `CDH_B_R07_001_REVIEW.zip` — `6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a`
  - `CDH_B_R09_001_REVIEW.zip` — `aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638`
  - `CDH_B_R10_001_REVIEW.zip` — `db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9`
  - `CDH_C_R10_002_REVIEW.zip` — `9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa`
  - `CDH_A_R11_004_REVIEW.zip` — `19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160`
  - `CDH_B_R11_002_REVIEW.zip` — `48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe`
  - `CDH_B_R12_003_REVIEW.zip` — `f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7`
- 不需要 Node.js 才能日常啟動；前端已編譯在 `apps\price-web\frontend\dist`。

## 啟動、查看狀態、停止

1. 在專案最上層雙擊 `Start-CDH-MVP.cmd`。雙擊模式會保留結果供閱讀；命令列傳入參數時不會 `pause`，並會保留 PowerShell 的真實退出碼。
2. 看到「本機價格歷史網站已就緒」後，把以下網址貼到瀏覽器：

   `http://127.0.0.1:4174/?mode=synthetic&contract=v4`

3. 要確認執行狀態，雙擊 `Status-CDH-MVP.cmd`。
4. 使用完畢雙擊 `Stop-CDH-MVP.cmd`。停止程序只會關閉收據與控制權杖一致的本專案實例，不會依 PID 強制終止未知程序。

PowerShell 使用者也可以執行：

```powershell
.\scripts\windows-mvp\Start-CDH-MVP.ps1
.\scripts\windows-mvp\Status-CDH-MVP.ps1
.\scripts\windows-mvp\Stop-CDH-MVP.ps1
```

## 四個日常操作

### 搜尋合成示範商品

頁面下方「搜尋 B10 商品、SKU 或商品 ID」只讀取已封存的 `SYNTHETIC_FIXTURE`，用來展示券前價、具有完整證據的已確認券後價及每日代表價。它不是即時酷澎資料。

### 手動記錄一筆價格

在「私人手動價格觀測」輸入商品身分、觀測日期與價格，先預覽，再勾選明確確認後保存。未知價格不會被當成零元；自報券後價保持 `USER_REPORTED`，不會升格為平台已確認價格。

### CSV／JSON 批次匯入

在「批次匯入私人價格」選擇符合 B16 契約的 UTF-8 CSV 或 JSON。上限為 1 MiB、500 筆。前端本地預覽後仍需取得伺服器預覽，只有逐筆錯誤為零且使用者再次明確確認，才會寫入隔離的私人 SQLite。HTTP 422 錯誤必須修正後重新預覽。

### 查詢已儲存的私人歷史

在「已儲存的私人商品」以名稱、商品 ID 或 SKU 搜尋。重新啟動網站後不需要重新提交資料，仍可讀取券前歷史、使用者自報券後歷史，以及證據符合時才存在的平台已確認券後歷史。單純查詢不新增觀測。

## 畫面上的資料分類

- `SYNTHETIC DEMO`：離線合成展示，不能當成真實酷澎價格。
- `PRIVATE USER-REPORTED`：使用者在本機輸入或匯入的私人資料，不是平台驗證。
- `PLATFORM CONFIRMED`：只有完整優惠券、資格、效期、範圍與來源證據都通過時才可顯示；不會由自報價格自動升格。

正式推薦／分潤按鈕仍停用，網站不建立任何正式外連或購物操作。

## 資料與日誌位置

- 私人歷史：`data\private_user_observations_b15`
- 啟動狀態與本機 runtime：`data\local_mvp`
- A16 啟動日誌：`logs\A16`

這些位置都在唯一專案根目錄內。請勿把私人 SQLite 複製到交件 ZIP。

## 錯誤排除

- `PYTHON_NOT_FOUND`／`PYTHON_TOO_OLD`：安裝 Python 3.11 以上，或建立專案內 `.venv`。
- `PINNED_RELEASE_MISSING`：上述 8 份正式相依 ZIP 之一不在 `review\releases`；錯誤會列出精確檔名與路徑。請恢復原檔，不要用改名檔替代。
- `PINNED_RELEASE_SHA256_MISMATCH`：相依 ZIP 位元不符；停止使用並交由維護者確認。
- `FRONTEND_BUILD_MISSING`：已編譯前端或其 Manifest 缺失；不可用開發伺服器冒充正式啟動。
- `PORT_IN_USE`：`127.0.0.1:4174` 已被使用。不要終止未知程序；先確認來源，或由測試人員以 `-Port` 指定隔離連接埠。
- `STALE_RECEIPT_MANUAL_REVIEW`／`PROCESS_IDENTITY_MISMATCH_MANUAL_REVIEW`：狀態收據與實際程序不一致。工具會 fail closed，不會強制刪除狀態或結束程序。
- 頁面顯示 API 錯誤：保留畫面訊息與 `logs\A16` 日誌；不要把失敗回退成合成 fixture 成功。

啟動器不會自動安裝套件、修改防火牆、讀取 `.env`、使用日常 Firefox Profile、連線酷澎或執行任何購物交易。
