# A16 Windows 本機價格歷史 MVP

此工具只在 `127.0.0.1` 啟動本機網站、精確 B11 合成唯讀 API、B15 私人手動觀測 API 與 B16 REV3 批次匯入 API。每次啟動都會驗證 A10 R08、B11、B13 R09、B14 R10、C11 REV2 R10、A14 R11、B15 REV2 與 B16 REV3 共 8 份直接／間接 release 的完整 SHA-256；不讀 `.env`、不連線酷澎、不自動開啟瀏覽器、不建立背景自動啟動。

日常使用請從專案根目錄雙擊 `Start-CDH-MVP.cmd`，並先閱讀 `docs/user-guides/WINDOWS_LOCAL_MVP_FIRST_USE.md`。下列舊入口保留供相容測試與工程診斷。

## 啟動

雙擊 `Start-LocalPreview.cmd`，或在 PowerShell 執行：

```powershell
.\Start-LocalPreview.ps1
```

命令成功後會印出 `http://127.0.0.1:4174/?mode=synthetic&contract=v4`。請自行貼到任意測試瀏覽器。若連接埠已占用，工具會以 `PORT_IN_USE` 停止，不會終止其他程序。

## 狀態與停止

```powershell
.\Status-LocalPreview.ps1
.\Stop-LocalPreview.ps1
```

停止只會對收據與隨機控制 token 綁定的同一個 A11 instance 發送 loopback shutdown；它不會依 PID 強制終止未知程序。若收據、token 或 instance 不一致，會以 `MANUAL_REVIEW` 狀態 fail closed。

## 邊界

- 合成 Search／Detail 資料分類固定為 `SYNTHETIC_FIXTURE`；私人手動與批次資料固定為 `PRIVATE_LOCAL_USER_ENTERED`，兩者不混合。
- B11 snapshot 以唯讀模式開啟，來源 release SHA 固定為 `6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a`。
- B15 REV2 來源 release SHA 固定為 `48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe`；前端只透過同源 `/cdh-private-observations` 代理連接，代理不接受任意 upstream。
- B16 REV3 來源 release SHA 固定為 `f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7`；批次預覽使用 base64 envelope，預覽不寫入，只有再次明確確認才保存。
- B15 REV2 store 明確綁定專案根目錄作為 `allowed_project_root`；資料根目錄必須在其下，且沿途 symlink、junction、reparse point 防護由精確 B15 程式執行，不在 A13 放寬。
- B15 寫入目錄可用 `control.py --private-data-root <path>` 明確指定；自動測試只使用 `reports/A13_REV2/browser_runtime/<run>/private_data` 隔離資料庫。
- 寫入前必須先取得 B15 session／CSRF、完成 server preview，再由使用者勾選明確確認；保存後以 B15 Search／Detail 回讀三條歷史。
- 前端基準 A10 R08 SHA 固定為 `0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd`。
- API 失敗時不回退 fixture；使用者會看到明確失敗與手動重試。
- 畫面上的零元是商品觀測價，不代表含運或必要費用後的零元結帳。
