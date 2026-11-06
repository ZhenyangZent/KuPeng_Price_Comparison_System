# E23 歷史 release 分批公開審查

TASK_ID：`CDH-E23-GITHUB-REPOSITORY-CONSOLIDATION-20261106`。基準為 `RELEASE_LEDGER.csv` 原有的 140 份歷史 ZIP，排除本任務自身 E23 REV1／REV2。依檔名穩定排序，每批 20 份，保存 `batch_00.json` 至 `batch_06.json`；七批沒有重掃已存在的 checkpoint。

## 實測結果

- 140/140 原始 ZIP 與本機台帳完整 SHA-256 相符，沒有同 SHA 的重複原件。
- 6 份通過文字成員、CRC、Manifest、路徑、無巢狀 ZIP、無私人資料庫／憑證路徑及內容模式檢查，也有精確中央 RECEIVED 台帳紀錄。
- 134 份維持 `BLOCKED_FOR_UPLOAD`。原因可重疊：敏感成員路徑 88、巢狀 ZIP 53、非文字成員 51、大型成員 12、私人 Windows 路徑模式 7、email 模式 6、電話模式 2、第三方來源審查 1。此處的「模式」是保守訊號，未斷定是真實憑證或個資。
- 對已由 ZIP 中央目錄判定有巢狀 ZIP、資料庫、影像或敏感路徑的封存，未開啟其內部成員、未測完整 CRC 或冒稱 Manifest PASS；該部分 gate 標記 `NOT_RUN`，原件保持本機。
- 六份符合門檻的原始位元組已上傳為 GitHub 歷史封存 prerelease：`https://github.com/ZhenyangZent/KuPeng_Price_Comparison_System/releases/tag/archive-safe-history-20261107`。GitHub API 遠端資產檔名、大小、SHA-256 digest 6/6 與本機及收件台帳相符，實際下載 URL 已寫入 `RELEASE_LEDGER.csv`。

此 prerelease 明確標示非產品上線。A15 舊 UI 預備 checkpoint、C08 離線映射、E 舊治理 checkpoint 和 G10 環境診斷均不因公開下載而升格功能驗收。H13 REV1 仍是有效 FAIL 報告，A17 正式 Runtime 亦未由 GitHub `main` 提供完整下載。

## 掃描與儲存限制

使用 GitHub Releases 資產，不使用 Git LFS 或一般 Git 歷史存放 ZIP。GitHub 官方目前允許單個 Release asset 小於 2 GiB、每個 Release 最多 1,000 個資產；本批六份遠低於限制。規則式文字掃描不能證明所有未審查圖片、二進位或巢狀內容均安全，所以 134 份不發布。參考：[GitHub Releases 文件](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。
