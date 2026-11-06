# Coupang Deal Hunter｜酷澎比價系統

目前最新中央限定驗收基準是 A17 Windows 本機整合試用版 `CDH_A_R13_001_REVIEW.zip`，SHA-256 `5de6b85e72767e8135b7ff0e6e3acb534965d5f636f61eea918cb082b02a8237`，裁決 `PASS_SCOPED`。H13 REV1 已由中央確認為有效失敗報告，搜尋測試工具待修訂，不能宣稱首次試用產品流程全線通過。正式酷澎商品擷取、推薦／分潤及公開部署仍未授權。

Windows 10／11 與 Python 3.11 以上的試用方式見 [A17 首次使用說明](docs/user-guides/WINDOWS_TRIAL_FIRST_USE_A17.md)。在完整 A17 Runtime 的專案根目錄使用 `Start-CDH-Trial.cmd`、`Status-CDH-Trial.cmd`、`Stop-CDH-Trial.cmd`；網址為 `http://127.0.0.1:4174/?mode=synthetic&contract=v4`。私人歷史位於 `data/A17_private_history/`，不得提交 GitHub。GitHub 鏡像如未包含經安全檢查的完整 Runtime，不能僅靠鏡像宣稱可獨立啟動。

新接手者請依序閱讀 [最短接手入口](docs/00_START_HERE.md)、[主交接](docs/HANDOFF/MASTER_HANDOFF.md)、[目前狀態](docs/HANDOFF/CURRENT_STATE.json) 與 [GitHub 同步規則](docs/HANDOFF/GITHUB_SYNC_POLICY.md)。

## 舊版 C01 純核心與 A16 MVP 說明（歷史）

下列 `Start-CDH-MVP.cmd` 與 C01 純核心段落是歷史版本資料；目前試用基準為 A17 的 `Start-CDH-Trial.cmd`。GitHub `main` 尚未包含完整 A17 Runtime，請先核對正式整合包，不能只靠文件 checkout 啟動網站。

## Windows 本機價格歷史網站

日常使用不需要進入工程子目錄：先閱讀 [`docs/user-guides/WINDOWS_LOCAL_MVP_FIRST_USE.md`](docs/user-guides/WINDOWS_LOCAL_MVP_FIRST_USE.md)，再於本目錄雙擊 `Start-CDH-MVP.cmd`。網站就緒後使用 `http://127.0.0.1:4174/?mode=synthetic&contract=v4`；結束時雙擊 `Stop-CDH-MVP.cmd`。

本機 MVP 支援搜尋離線合成示範、手動記價、CSV／JSON 批次匯入與私人歷史查詢。它不自動開啟瀏覽器、不連線酷澎、不修改 Registry；正式推薦／分潤功能維持停用。

`cdh-core` 是 V3.0 規格第 7–11 章的純本地、離線參考實作。它只處理合成資料的金額、證據、歷史基準、決策與 SQLite Outbox；不連線酷澎或任何第三方、不操作 Firefox、不購物，也不傳送真實通知。

## 從原始碼執行

需要 Python 3.11 以上，不需要第三方套件或套件安裝：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
python -m cdh_core.demo --fixtures tests\fixtures\demo_cases.json --db review\R04\evidence\after\demo.sqlite3 --output review\R04\evidence\after\demo_results.json
```

金額一律使用 TWD minor units（NT$1 = 100），例如 `900` 代表 NT$9。對未知費用、資格衝突、資料過期及情境不一致採 fail-closed。

## 模組

- `models.py`：型別、狀態與同情境證據約束。
- `pricing.py`：固定 q 的完整必要成本計算、型別化費稅處置證據、已含費用證據、優惠券期限傳遞與顯式條款。
- `history.py`：UTC 小時取樣、Asia/Taipei 日界及 M7/M30/M90。
- `policy.py`：單一 S0/S1/S2/S3/TARGET/O1/O2 政策、完整政策證據與程序內核准封印。
- `persistence.py`：SQLite schema v5 保留式 migration、單調商品 current-state、獨立使用者／情境通知政策 epoch、穩定語義去重、事件／Outbox 原子提交與送出前後重驗。
- `demo.py`：合成 fixture CLI 與 mock delivery。

`v0.5.0` 的 quote、policy context、history baseline、decision、current state 與 event 均綁定完整 scenario scope。最早依賴期限會一路縮短到 event；任意字串不能將費用或稅費歸零；只有版本化 allow-list 內的完整購買價格基準能進入通知政策；入隊要求政策引擎對完整證據做程序內核准。產品標記：`OFFLINE_ONLY`。`DELIVERED` 只代表 mock sink 已完成，不代表外部 exactly-once。
