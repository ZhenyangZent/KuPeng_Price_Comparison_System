# A04 架構與信任邊界

`MainWindow` 只負責表單、唯讀狀態與明確確認；正式 SQLite 寫入只由凍結的 `scripts/d03/local_operator.py` 執行。`D03Client` 以固定 argv、`shell=False`、專案固定 Python、單一程序 guard、timeout／cancel 與嚴格 JSON 驗證包住五個既定命令。

Dry-run 回覆的 plan 有 10 分鐘本機顯示期限。真實安全判定仍由 D03 在 execute 時重新驗證 plan hash、狀態身分、預覽、writer lock、備份與一次性消耗；GUI 的期限檢查是額外的提早阻擋，不替代 D03。

錯誤邊界要求 `BLOCKED`／`FAILED` 必須帶 `{code, detail}` 物件，非零返回碼即使 stdout 可解析也不會被顯示成成功。execute 成功後 A04 會自動 Verify，再讀 receipt、snapshot 與歷史。

D04 介面只是一份 A 線提案，詳見 `CONTRACT_PROPOSAL.md`。它不修改 D04，也不代表 D04 已獲中央 Orchestrator 接受。

