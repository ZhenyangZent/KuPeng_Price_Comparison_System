# 新接手者從這裡開始

1. 先讀 `README.md`、`AGENTS.md`、`docs/RULES/PROJECT_GUARDRAILS.md`。
2. 讀 `docs/HANDOFF/CURRENT_STATE.json` 與 `docs/HANDOFF/MASTER_HANDOFF.md` 的最後一節。中央 ACK 是收件；只有明示的中央裁決能作為功能驗收狀態。
3. 用 `docs/HANDOFF/RELEASE_LEDGER.csv` 核對正式版本的完整 SHA-256。不可憑同名或工作目錄推斷版本。
4. Windows A17 試用依 `docs/user-guides/WINDOWS_TRIAL_FIRST_USE_A17.md`。私人資料與執行期目錄留在本機，不進 GitHub。
5. 新任務只修改授權工作線。先做隔離合成測試，再交 REVIEW／STATUS_ONLY；中央精確 ACK 後才歸檔待上傳副本。
6. GitHub 更新依 `docs/HANDOFF/GITHUB_SYNC_POLICY.md`；未驗收候選不可冒充預設分支採用版本。

目前 A17 `PASS_SCOPED`；H13 REV1 已由中央收到並確認是有效的失敗證據，搜尋測試工具須修訂，不能宣稱 H13 已通過。GitHub 歷史封存 prerelease 只包含經個別審查的六份舊 ZIP，與正式產品發布無關；其餘 134 份的阻塞原因見 `reports/E23/release_audit/SUMMARY.json`。
