# GitHub 同步規則

GitHub 是公開的程式與交接入口；Windows 專案根目錄仍是隔離執行、私人資料與不可發布證據的保管處。`RECEIVED` ACK 只代表中央收到候選檔案，不能取代產品或安全驗收。

1. 每輪保存不可覆寫的 REVIEW／STATUS_ONLY 原件、SHA-256、中央裁決與失敗證據。
2. E 先核對上游身分、目前遠端 HEAD、分支保護與其他工作線的活動，再建立隔離同步候選。
3. 逐檔以 `GITHUB_UPLOAD_INVENTORY.csv` 判定來源與上傳資格；檢查純文字機密、個資、二進位、巢狀 ZIP、圖片、日誌及資料庫。未知或可疑項留在本機，標 `BLOCKED_FOR_UPLOAD`。不讀取正式 `.env` 或私人資料庫的內容來換取發布資格。
4. 一般原始碼、規則、測試和安全文件可同步；未驗收候選只能留在隔離分支，不能寫成預設分支採用基準。
5. 正式 release 的索引保留每版 SHA、裁決與下載 URL。只有逐份完整檢查後才上傳 GitHub Release／LFS；同 SHA 不重複上傳，不用巢狀 ZIP 規避限制。
6. 提交前檢查 staged diff、`git diff --check`、受影響測試與遠端基礎 SHA。禁止 force push、歷史改寫、`git clean -fdx`、`git reset --hard`。
7. 推送後重新讀取遠端 SHA；記錄 TASK_ID、分支、commit、版本、中央裁決、已同步與排除檔案。失敗保留本機 checkpoint，不宣稱成功。
8. 若發現可能已外洩的憑證，停止受影響發布並要求撤銷／輪替；不得靠刪除新版本聲稱歷史已清除。

本規則不授權定時自動推送、正式部署、資料來源開通或分潤操作。每次同步仍需符合當次任務權限與上述 gate。
