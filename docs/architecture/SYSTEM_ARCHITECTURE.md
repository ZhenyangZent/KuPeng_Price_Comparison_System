# 系統架構與邊界

- `apps/price-web/local-trial-a17`：A17 Windows 本機試用入口與整合 Runtime；根目錄 CMD 管理啟停。
- `apps/price-web`：合成展示、搜尋、手動輸入、批次匯入預覽與私人歷史 UI。
- `services/price_query*`、`services/price_coupon_v4`：合成價格查詢與券前／券後歷史模型。未知費用、券資格與證據維持 fail-closed。
- `services/private_observation_b15`、`services/private_batch_import_b16`：本機 Session／CSRF、預覽、明確確認、隔離 SQLite 與私人搜尋。B16 REV3 是 A17 的綁定版本。
- `src/cdh_core`：離線純核心、歷史、政策與 mock outbox，沒有真實通知投遞權限。
- Firefox Native Messaging、通知、資料來源研究與分潤模組只保存研究／離線門檻。未獲准存取日常 Firefox、真實酷澎來源、正式通知或分潤點擊。
- GitHub 是已審查的程式／文件鏡像；私人歷史、日誌和未審查 release 留在 Windows 專案根目錄。

資料流：使用者本機 UI → 受限 loopback API → 隔離私人歷史 SQLite → UI 搜尋／歷史。合成示範資料與私人觀測分區；使用者自報券價絕不當作平台確認價。
