# Windows runner 與 headless 限制

- `windows-latest` 映像與預裝版本會變動；JSON 會記錄實際 Python／Node／npm 版本，不能只相信 workflow 標籤。
- 本專案的前端測試只在本地 Vitest module 存在時執行。缺 `node_modules/vitest/vitest.mjs` 時是 `NOT_EXECUTED_DEPENDENCY`，不是 PASS。
- PySide6 目前在 G02 本機不存在。A04 GUI 測試即使日後有 PySide6，也會因寫入 owner lane 而由 G02 標記 policy skip；應由 A 工作線或乾淨、受批准的 CI workspace 執行。
- Python Playwright 目前不存在；headless browser、瀏覽器下載與 display backend 均未由 G02安裝。不可用「沒有看到錯誤」推論 E2E 已執行。
- loopback E2E 必須固定 `127.0.0.1`、使用明確 port、等待健康檢查、確實終止 child process，且禁止 wildcard CORS 或使用者可控 proxy destination。
- GitHub-hosted runner 不是離線環境。若中央未批准網路與第三方 actions，應改用已封存工具鏈的自管隔離 runner，並把其 image digest 納入 source identity。
- 真實 `.env`、Cookie、Registry、酷澎登入與 Partner token 不得成為 CI prerequisite；只使用合成 fixture。
