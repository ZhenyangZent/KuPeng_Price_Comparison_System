# 私有 GitHub Actions 預覽（未啟用）

此目錄只是中央日後批准私有 repository CI 時可採用的範例；它不在 `.github/workflows`，因此不會自動執行。本輪沒有建立遠端 repository、push、部署、讀取 GitHub secrets 或發出任何酷澎請求。

## 本機先行

```powershell
python -m tools.ci_offline.check_project `
  --suite g02_self `
  --suite frontend_vitest `
  --scan-source tools/ci_offline `
  --scan-source tests/ci_offline `
  --output-dir reports/G02/local
```

Runner 只使用已存在的 Python、Node 與本地 `node_modules`。缺依賴時回傳 `3` 並標記 `NOT_EXECUTED_DEPENDENCY`，不會呼叫 `npm install`、`npx` 或 `pip install`。

## 啟用前的必要決策

1. 中央 Orchestrator 明確指定私有 repository、branch protection、GitHub Actions authority 與第三方 action pinning。
2. 決定依賴如何由受信任、固定版本的離線 artifact 或 lockfile 提供；此 preview 不授權下載。
3. 將範例複製到 `.github/workflows` 前重新審核權限、網路、artifact retention 與 fork/PR secrets 邊界。
4. 正式 workflow 不得讀根目錄真實 `.env`，也不得接收酷澎帳號、Cookie、Partner token 或付款資料。
5. 瀏覽器、PySide6、Windows GUI 與本機 loopback E2E 必須分 job 且明示依賴；未執行不得顯示 PASS。

輸出為 `check_project.json`、`check_project.junit.xml` 和逐 suite stdout/stderr，可由將來的 CI artifact step上傳；本輪沒有執行上傳。
