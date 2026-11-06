# Coupang Deal Hunter｜中央 Orchestrator 主交接檔

**版本：2026-11-04 H1／取代單純對話式交接**
**狀態：多 Codex 並行開發；本文件為路徑與交接單一入口，不表示產品已正式上線。**
**維護者：中央 Orchestrator（ChatGPT）；執行者：Codex A、B、C、D、E；必要時新增 F。**

> **閱讀順序：本檔 → `PROJECT_FILE_INDEX.csv`（實機產生）→ `EXTERNAL_PATH_LEDGER.csv` → `review/releases/` 各任務交件與報告。**
> **可信程度：本文件的檔案雜湊已在本次上傳 ZIP 中核對；Windows 原始硬碟的完整清單及外部例外路徑，仍須由 Codex 在該電腦實機盤點，不能憑 ZIP 宣稱全部存在。**

---

## 1. 唯一合法根目錄與保留原則

```text
LOCAL_USER_HOME\Music\University\program\酷澎比價系統
```

任何原始碼、資料庫、使用者輸入、文件、測試、工作日誌、錯誤紀錄、ZIP、腳本、模型輸出與暫存成果，**預設必須在根目錄及其子目錄內**。含中文路徑是正常情形；不要因為方便就將專案搬到桌面、Downloads 或另一個專案。

只有在第三方工具不可避免的限制（例如程式無法處理中文、外部 CI Runner 的短暫工作目錄、作業系統強制位置、可重現路徑 Bug）時才容許例外：**先在根目錄內嘗試 ASCII 命名子目錄；無法解決才使用根目錄以外路徑，並在 `docs/HANDOFF/EXTERNAL_PATH_LEDGER.csv` 記錄精確絕對路徑、內容、原因、建立者、任務、建立時間、是否暫存、清理時機與核對狀態。** 不能用「測試而已」略過登錄。

- 禁止自動刪除不明舊檔，不覆蓋已存在交件與重要資料。移動或封存需保存原始 SHA-256、移動前後位置及操作收據。
- 專案不是 Git repository（截至目前 Codex 回報），不能宣稱已完成 Git commit/push。
- 根目錄 `.env` 為機密，只由後端本機讀取。不得覆寫整份檔案；不得存進聊天、Git、前端、截圖、日誌、ZIP 或雲端測試。可提供無金鑰的 `.env.example`。
- 所有 Codex 指令必須清楚標示「丟給 A／B／C／D／E／F」與授權白名單。

## 2. 建議專案目錄地圖（須在真實 Windows 上核對）

```text
酷澎比價系統/
├── .env                                 # 僅本機秘密；禁止打包/同步/曝光
├── .env.example                         # 只含空白/假值；可入版本庫
├── README.md                            # 專案入口
├── apps/
│   ├── a01/                             # A：Windows Qt GUI（A01→A04）
│   ├── d01/                             # B：SQLite 商品觀測／匯入
│   ├── d03/                             # B：本地同步操作器
│   ├── s01/                             # C：使用者提供的線索處理
│   └── n01/                             # D：MockSink 通知事件
├── src/                                 # C01 價格核心、I01 合成整合
├── scripts/
│   └── orchestrator_handoff/            # E：交件工具（待改平面多 ZIP）
├── tests/                               # 各工作線回歸測試
├── docs/
│   ├── HANDOFF/
│   │   ├── MASTER_HANDOFF.md            # 本文件，最主要的接力入口
│   │   ├── PROJECT_FILE_INDEX.csv       # 執行檔案盤點腳本產生
│   │   ├── EXTERNAL_PATH_LEDGER.csv     # 根目錄外的所有例外
│   │   ├── UPLOAD_QUEUE_PROTOCOL.md     # 上傳→確認→歸檔 SOP
│   │   └── RECEIPT_LEDGER.jsonl         # 每批收件確認與原始雜湊
│   ├── specifications/                  # V3.0 產品規格與後續 ADR
│   └── ...
├── data/
│   ├── d01/observations.sqlite3         # 正式本地資料庫；勿由測試覆蓋
│   └── exchange/                        # inbox、receipts、snapshots、reports
├── experiments/                         # 合成資料／隔離 GUI／錯誤注入
├── reports/                             # 測試/驗收/風險/操作日誌
├── input/                               # Orchestrator 下發包與原始附件
├── review/
│   ├── releases/                        # 永不覆蓋的正式原始 review ZIP
│   ├── 00_TO_UPLOAD/                    # 唯一待上傳收件匣：平放各工作線 ZIP
│   ├── 90_UPLOADED_ARCHIVE/             # Orchestrator ACK 後歸檔的上傳副本
│   └── ...                              # 各輪可追溯證據
├── apps/web/                            # 計畫中：未宣稱已存在
└── services/affiliate/                 # 計畫中：未宣稱已存在
```

**目錄標註「計畫中」不代表已建立。** `docs/HANDOFF/MASTER_HANDOFF.md` 是建議要把本份交接下載並放入的路徑。若既有同名檔，先核對內容版本，禁止盲目覆蓋。

## 3. 產品目標（最新優先順序）

**最高優先 MVP：** 台灣酷澎商品的「已收錄商品搜尋／查詢歷史價格網站」＋「商品頁開啟使用者自己的對應商品推薦／分潤連結」。後端讀根目錄 `.env` API 配置，先核實台灣官方 API／Partners 的實際權限、商品連結轉換能力與條款；不能假設有 Affiliate API 就有完整商品／歷史價抓取許可。

MVP 至少包含：可搜尋已收錄商品、同 SKU／賣家／包裝比較、價格歷史的真實觀測時間與有效覆蓋天數、最後觀測價與觀測期間低點、導向該商品的個人連結按鈕、商品資料缺失與轉換失敗狀態、來源／時間／會員價型明確標示。不能把模擬價格或宣傳劃線價當歷史成交價。

**延後而不取消：** WOW 會員免運優惠通知、非免運超級便宜 O1/O2 例外、0 元雷達、Windows GUI、Telegram；這些不是第一個歷史價網站上線的前置條件。

**硬性安全規則：** 僅查詢、分析、提供由使用者主動點擊的商品頁連結；永久禁止自動領券、加入購物車、進入結帳、下單或付款。沒有真實資料使用授權，不啟動酷澎全站或登入頁背景蒐集。

## 4. 已知工作線與可被信任的進度

| 工作線 | 短名／基準 | 已完成的限定成果 | 仍未驗證或阻塞 |
|---|---|---|---|
| 核心 C01 | v0.5.0、Schema v5 | R04 經中央獨立驗收，離線價格/資格/事件/SQLite Outbox | 真實資料入口與外部通知 |
| G0 | SOURCE_BLOCKED | 台灣商品來源研究完成 | 未確認可持續自動蒐集及驗證資格的適用授權來源 |
| B01 | Phase B | 隔離 Firefox 與 Native Host 的合成 E2E，含重啟/故障回復通過 | 未接日常 Firefox/真酷澎；指定 HKCU 測試鍵仍有 marker-only 殘留，刪除需另批准 |
| I01 | R01 | 合成 Observation→C01→SQLite→MockSink 限定驗收通過 | 未接真實商品來源 |
| A | A01/A02/A03 → A04 | Windows 本機手動觀測、CSV、D03 安全同步 GUI；A04 提供 Windows 原生視窗記錄 | 本輪 A04 已核對封存與部分程式測試；Windows GUI 尚非本審核環境親自執行；D04 報表仍未接通 |
| B | D01/D02/D03；D04 待交 | SQLite 觀測/快照/回執、離線安全操作器；D03 本輪已重跑 42/42 | 尚未確認正式使用者資料同步啟動；D04 新報表未見獨立交件 |
| C | S01 | 人工 CSV/文字情報線索，資格維持 UNKNOWN；本輪 13/13 PASS | 真實自動來源授權仍 SOURCE_BLOCKED |
| D | N01 | 合成通知 Outbox、撤銷、episode/去重，MockSink-only；本輪 36/36 PASS | 沒有真實 Toast/Telegram 通知 |
| E | E01 | ZIP 安全批次封裝與 ACK 後歸檔；本輪 18/18 PASS | 既有批次只含 E01；不能直接滿足多工作線平面全選上傳，需修改契約 |
| F（預留） | Affiliate API | 分潤／推薦連結後端轉換與秘密保護 | API 類型/台灣覆蓋與實際端點未核實；尚未正式發令 |

先前正式限定驗收：A02-R01、D02、I02 已通過已定義的合成／離線範圍；I02 不是實際酷澎自動更新或對外網站。**一律區分「Codex 自報」「Orchestrator 核對封存」「測試重跑」「真實 Windows E2E」「對外上線」五種不同證據階級。**

## 5. 2026-11-04 本批 ZIP 收件確認

中央本輪已收到以下 5 份上傳。以下 SHA-256 是實際本輪容器讀取檔案而得；CRC、路徑安全及 manifest 亦核對。`D03_001_REVIEW(1).zip` 與先前同名無 `(1)` 的 D03 交件位元完全相同，屬重複傳送。

| 工作線 | 本輪附件 | bytes | SHA-256（完整） | Manifest檔數 | CRC |
|---|---|---:|---|---:|---|
| A | `CDH_A04_001_REVIEW.zip` | 13,833,209 | `c40ef108465f79d2833060265785638d9cac9ee99f3900d3238eae01afb7ad8d` | 153 | PASS |
| D | `CDH_D03_001_REVIEW(1).zip` | 4,533,730 | `60828a08addd81d880449dd17b88df2dcc8e5dc31f360348ec94feca7393ae22` | 108 | PASS |
| N | `CDH_N01_001_REVIEW.zip` | 167,720 | `1954d9ba67771a6f4b0d70c0518c15d1953907dc269c961038a5ae44d66c40cc` | 62 | PASS |
| S | `CDH_S01_001_REVIEW.zip` | 72,150 | `8b675ee51672b6d5616b6afe31ebd37324a73a1c29c144dc3613e01868c746e6` | 44 | PASS |
| E | `CDH_BATCH_20261104_E01_001_REVIEW.zip` | 24,652 | `c484fb330f518d9df42509dbc229d361b40c57beafd78585293b3ab3f637aafd` | 0 | PASS |

E01 外層批次檔只有 `BATCH_MANIFEST.json` 與 `packages/CDH_E01_001_REVIEW.zip`；內層 SHA-256 為 `24687f2871f6528dc0565029ff81a16ecac9d85a66fa342fc503885b23378881`，13/13 payload 雜湊一致。**它沒有包含 A04、D03、N01 或 S01。** 不應因存在 E01 的 batch，就把其餘交件誤標為已在內包。

**本輪實際可攜式測試**：S01 13/13、N01 36/36、D03 42/42、E01 18/18 PASS。A04 的 10 項指定 `tests/a04` 在 Linux 執行時 8 項通過，2 項由於缺少 PySide6 和 Windows `msvcrt` 無法重現；Codex 交件含 Windows 原生 GUI 證據，但本次沒有在使用者電腦上重做。以上為本批目前核驗範圍，**沒有宣稱全部 5 條線已完成產品級最終獨立審查**。

另有機器可讀的 `RECEIVED_UPLOAD_INVENTORY_20261104.json`，保存附件大小、hash、CRC、manifest、相容性狀態。

## 6. 「我全選 ZIP 給 ChatGPT」的正式新契約（取代強制單一 batch）

1. 工作線完成後，原始 immutable review ZIP 放在 `review/releases/CDH_<工作線>_<輪次>_REVIEW.zip`，絕不覆蓋歷史。
2. 將每份需要上傳的新交件 ZIP **複製（非移動原始）**至 `review/00_TO_UPLOAD/`，全部平面放置，不建立 A/B/C 子資料夾，也不混入 `.env`、CSV、PDF、截圖、舊版本或未完成 `.partial`。
3. E 工具核驗：檔名白名單、SHA-256、ZIP CRC、Manifest、路徑安全、禁止 secrets、不要混入 2 層 ZIP。使用者直接 Windows 檔案總管 `Ctrl+A` 全選這些 ZIP 上傳，無需逐條找路徑。
4. ChatGPT 對每個精確檔名和 SHA 回報 **RECEIVED**（不表示測試已 PASS），才可歸檔對應的上傳副本。未被確認的檔案留在待上傳夾。
5. 下一輪 Codex 收到 ACK 後，E 對符合精確 hash 的上傳副本執行安全移動，放至 `review/90_UPLOADED_ARCHIVE/<批次時間>/`，留下 `ARCHIVE_RECEIPT.json`（before/after path/hash/ACK/時間）；`review/releases/` 的原始檔原封不動。
6. 遇到部分到齊、重複檔名或 hash 不符時，只處理已確認的項目；不整夾刪除、不覆寫、不擅自封存。下一批開始前 `00_TO_UPLOAD` 只留未 ACK 項目，避免重傳。
7. 舊 E01 「只容許一個先生成 batch 且不能再加入」要修正：**以平面 queue 為主，單一總包僅使用者另外指定時才生成，且須等各線完成後才封裝。**

> 使用者本輪已分別上傳 A04、D03（重複副本）、N01、S01、E01 批次。下一次交件不必再上傳完全相同 SHA 的這些檔案。

## 7. 外部路徑的唯一例外簿

維護檔案：`docs/HANDOFF/EXTERNAL_PATH_LEDGER.csv`。最低欄位：`record_id,path,created_by,task_id,why_external,content_type,created_at,temporary,expiration_or_cleanup,authority,verified_at,status`。

目前能從交件推知的可能例外：

- **Windows Registry**：`HKCU\SOFTWARE\Mozilla\NativeMessagingHosts\com.coupang_deal_hunter.b01_poc`，此前授權合成 E2E 後存在 marker-only 鍵；不是檔案系統位置。**未授權刪除**，須列在資源例外／狀態表中，不能視為已清理。
- **OS Temporary、Windows 程式套件與 Qt 平台插件**：若硬性依賴系統安裝路徑或 CI Runner，可使用系統位置，但測試檔案與報告應返回 root；例外簿記錄實際路徑，不能只寫「TEMP」。
- **遠端 GitHub／Actions**：它不是本機資料夾。需記錄 repository、visibility、branch、commit、run URL、artifact、觸及的秘密範圍與保留期間。尚未建立 repo 不能填假網址。

交接檔無法查出使用者電腦所有外部檔案；要由被授權 Codex 執行真正的 Windows 路徑盤點，將結果更新至上述 CSV。

## 8. A04 為何用你的螢幕？之後優先不打擾

A04 自帶 `reports/A04/001/WINDOWS_GUI_EVIDENCE.md`，明確記錄使用 `apps/a01/.venv/pythonw.exe -m a01_app.main` 啟動 **PySide6/Qt 原生 Windows 視窗**，Windows UI Automation 檢查四個頁面與控制項、保存 PNG、再以 `Alt+F4` 關閉。此為 GUI 實機測試，不是 Python 網站；交件紀錄稱沒有啟動 Firefox 或連線酷澎。視窗可能出現在使用者桌面、搶焦點，這是桌面程式測試的正常副作用。

**新原則：** 純 Python／資料庫／靜態網站與 Playwright 等測試優先在無頭環境、CI 或隔離 VM 執行；Qt GUI 盡可能使用 Qt offscreen 和 GitHub Actions Windows Runner；只有真正要測的 native UI interaction、印表機、系統匣或特定 Windows 設定，才安排隔離 Windows GUI 實測並在任務中明確標示「會有視窗」。不得在無必要時擅自啟動日常 Firefox 或任何購物分頁。

## 9. GitHub 與線上網站測試策略

**允許設計及提案，但未持有 repository、visibility、branch、認證及部署參數前不得自動公開上傳。** 優先用私人 Repository 收納無密鑰程式碼，GitHub Actions 使用 Linux/Windows CI Runner 重跑測試和產出工件；避免占用使用者桌面。

- GitHub Pages 適合**靜態**商品網站／前端預覽，**不能直接執行 Python 後端**。要用 API 金鑰轉換分潤連結，必須另有受保護的伺服器端環境（或只部署假資料、無秘密的靜態 Demo）。
- 若需真正外部網站，可另選受控後端平台；遷移機密只能用平台 Secrets 而非將根目錄 `.env` 上傳。資料庫是否允許公開展示與資料源授權仍要審查。
- CI/部署事件要記到 docs/HANDOFF/EXTERNAL_PATH_LEDGER.csv 或 REMOTE_RESOURCES.csv，避免交接人不知道哪個網站、工作流、帳號、repo 是真的。
- **上線需獨立確認**：repo 可見性、網域、內容公開範圍、分潤合約及導購標示、API 金鑰權限與實際資料來源使用權。

## 10. 安全／資料規則（不可由其他工作線自行變更）

- 使用者是 WOW 會員，但「是否會員」是使用者陳述，實際頁面 SKU 可用免運和費用仍要驗證。**自動通知預設只在免運、資格、必要總成本有證據時放行**；非免運只在可信含運成本與參考價符合可調 O1／O2 時放行。
- 首購資格 `UNKNOWN` 不等於符合；未確認券、運費、費用、庫存一律 fail-closed，不得製造零元。
- 歷史價是本專案的觀測價，不是成交價；相同 SKU／數量／賣家／會員條件不得混寫。
- B01 的 Registry marker-only 鍵仍未獲刪除授權；已通過的合成 E2E 不等於可用你的日常 Firefox 取得資料。
- G0/S01 `SOURCE_BLOCKED`：尚未確認可合法持續自動收集台灣酷澎商品與會員資格的來源，不可自行開爬蟲。
- N01 MockSink 是測試用，不等於真實通知；網站分潤鏈接必須由官方允許的後端轉換流程產生。

## 11. 接手人的第一個小時：照這個順序

1. 閱讀此檔及 `docs/HANDOFF/PROJECT_FILE_INDEX.csv`、`EXTERNAL_PATH_LEDGER.csv`。
2. 確認本機根目錄是否存在、`.env` 只確認存在狀態、不開啟內容；絕不貼出機密。
3. 比對 `review/releases/` 與 `review/00_TO_UPLOAD/`，核對各工作線最新 SHA，不盲目從複查 ZIP 覆寫本機檔案。
4. 核對 A04（原生 GUI）、D03（操作器）、N01（MockSink）、S01（人工線索）、E01（上傳工具）各白名單與測試。**目前只完成本輪文件／封存／部分重跑，沒有核准正式部署**。
5. 新任務先追「歷史價網站＋自己的商品分潤連結」：優先確認台灣 API 正式文件、後端密鑰讀取、商品搜尋與前端價格歷史展示所需資料。
6. A/B/C/D/E/F 分工不可同時改同一受保護模組，必要時先定共同 schema 和接口，並記錄 ADR。
7. 對所有仍阻塞的外部資料權限、Registry 清理、GitHub 公開部署、正式同步或真通知，要求明確範圍授權；對純離線合成測試可採快速里程碑自動修正。
8. 每次中央複查結案，更新本檔「最近交件」和最新文件 hash，新增當輪決策、測試結果、風險與下一步指令。**文件不是只寫一次，而是每批交件後就維護。**

## 12. 下一批預計分工（方向，不是已授權執行命令）

| 丟給 | 建議較大工作里程碑 | 必要交付 |
|---|---|---|
| A | 歷史價查詢網站原型：搜尋／SKU商品頁／價格圖／導購按鈕的狀態設計 | 完整網站源碼、無頭端到端截圖、離線示例 |
| B | 既有 D01/D04 資料至網站查詢接口、索引與可靠觀測歷史 | 可重現 API、資料字典、測試、Schema Migration |
| C | 台灣酷澎 Partners/推薦鏈接 API 的類型、用途與文件核實 | 權限證據與 API 能力矩陣；不擅用金鑰 |
| D | 後端/網站資料安全與產品核對：來源、到手價、秘密曝光、轉換連結、分潤揭露 | CI 安全與反例測試 |
| E | 將 E01 改成平面多 ZIP 待上傳夾，建立路徑索引與自動更新主交接 | SHA 收據、外部路徑 ledger、交件排程工具 |
| F（必要時） | 後端聯盟導購網址轉換、過期快取與錯誤恢復 | 秘密不出 backend 的 adapter 與測試 |

## 13. 交接完整性的限制

本檔來自對話紀錄及 2026-11-04 提交的 5 份 ZIP；**不等於已盤點使用者 Windows 磁碟上的所有專案檔案**。本批上傳內容未揭露正式 `.env`、GitHub repo 或真實庫存 API 可用性，因此不能推論 API 功能已經接通。未完成的審核條目必須保留為 `PENDING`，不可為了進度好看改成 `PASS`。

---

**完成此檔後，請在專案根目錄的 `docs/HANDOFF/MASTER_HANDOFF.md` 保存版本，並按 `PROJECT_FILE_INDEX.csv` 進行當機盤點。此檔隨下批交件持續更新。**

## 14. E02 實機更新（2026-11-05 Asia/Taipei）

- E02 authority：`CDH-E02-FLAT-UPLOAD-AND-MASTER-HANDOFF-001`，僅本地 handoff automation。
- 使用者直接指定並由本機核對的輸入 package SHA-256 為 `f8292e7378f20891a68eb932e1f0678681964424de7b11ada510fba56dd3f298`。包內 E02 task 仍寫舊候選 SHA `77e687...`；此差異已記錄，不把舊值冒充本機 byte identity。
- 平面 queue 主工具：`scripts/orchestrator_handoff/flat_queue.py`。舊 `handoff_batch.py` 保留作 E01 相容與明確要求時的 legacy batch，不再作一般交件預設。
- 中央精確 ACK 的 E01 batch 副本已從 `review/00_TO_UPLOAD` 移至 `review/90_UPLOADED_ARCHIVE/20261104_ACK/`；原始 `review/releases/CDH_E01_001_REVIEW.zip` 未移動、未修改。
- A04、D03、N01、S01 雖列於中央收件 inventory，但本輪開始時不在 queue，E02 沒有重建後再假裝歸檔。
- `review/00_TO_UPLOAD` 新契約是平面、可多 ZIP、只含未 ACK 的完整 review ZIP；partial、hidden、非 ZIP、nested ZIP 與敏感路徑 fail closed。
- E02 本地測試與正式交件仍只代表 `READY_FOR_REVIEW`，不核准 A04／D04／N01／S01 真實上線、外部來源、真通知或交易。

## 15. 2026-11-05 Round 02 中央收件與 E03 整併

中央 Orchestrator 已用精確 SHA-256 複查下列六份交件；`RECEIVED`／限定 PASS 不等於正式上線：

| 工作線 | 本機 canonical release | 中央上傳檔名 | SHA-256 | 限定裁決 |
|---|---|---|---|---|
| A05 | `CDH_A05_001_REVIEW.zip` | `CDH_A05_001_REVIEW(1).zip` | `66652edfd641869ac63ea44c0254e712441fceccd77ea3bb78f706120cb14d0e` | 合成 React 預覽封存與交件證據成立；A/B 整合未驗收 |
| B05 | `CDH_B05_001_REVIEW.zip` | 同 canonical | `31ab7903f56dfc4fc339d6b04aea74eebb1fea257a4e69554202cafc4c8c953e` | copied SQLite read-only API 限定 PASS；非正式資料服務 |
| C02 | `CDH_C02_001_REVIEW.zip` | 同 canonical | `8aed0aea0f962db9a140cea2c87c7127f9645d1821ee7ef4545fec2a670ab8da` | 文件／安全契約研究限定 PASS；台灣 Partners 能力仍未證實 |
| D02 Web | `CDH_D02_WEB_001_REVIEW.zip` | 同 canonical | `fe9fb15143b472ac58c48104d059aea8f9184bee22e83104044be422d48fe100` | 安全 harness 39/39；`.env.example` false-positive 規則需修正 |
| D04 | `CDH_D04_001_REVIEW.zip` | 同 canonical | `0bd8d8a449257dfdb056e324033280f84c2c06479f8475553b6854cd31aaa2f3` | 離線唯讀歷史分析限定 PASS |
| E02 | `CDH_E02_001_REVIEW.zip` | `(1)` 與 `(2)` 同位元組 | `19735c499c6645509a1834560f154c51dbc103143955380d4508a25a64c6ce7b` | 平面 queue／handoff 36/36 限定 PASS；兩份只算一件 |

E03 已依上述 ACK 將六份本機 queue 副本移至 `review/90_UPLOADED_ARCHIVE/20261105_ROUND02_ACK/`，保存 canonical filename、中央 alias、before/after path、SHA、UTC time 與 exit code；`review/releases` 原件均未修改。

### 網站跨線凍結前差異

1. A05 需要 `data_classification`，B05 search/detail 缺欄位；不得 TypeScript 強轉掩蓋。
2. Affiliate DTO 一邊 nested、一邊 flattened，需凍結唯一 schema。
3. A05 宣稱名稱／SKU／規格搜尋，B05 實際只搜 title；variant 查詢現為 0。
4. B05 無 `item_condition` 來源欄位卻回 `NEW`，應降為 `UNKNOWN/null`。
5. Affiliate CTA 還缺官方 host、seller/variant、expiry/revocation 與台灣揭露證據；預設 disabled。
6. A05/B05 loopback port 不同且無同源 proxy/CORS 契約；禁止用公開 wildcard CORS 迴避。
7. `.env.example` 只能在嚴格 placeholder 檢查後允許；真 `.env` 永久禁止入包。
8. 整合先用 synthetic／獲准使用者副本，禁止以真實酷澎或第三方 API 試探。

### 目前任務身份索引

- A：`CDH-WEB-A06-FRONTEND-API-INTEGRATION-001`；本機交件 `CDH_A06_001_REVIEW.zip`（SHA-256 `d9fce75d876b86d5cbb28f77e8ff9354e9d38a5c9389abe10d2a2ddc46adefb5`）已進 queue，待中央 exact ACK
- B：`CDH-WEB-B06-PRICE-QUERY-CONTRACT-001`；本機交件 `CDH_B06_001_REVIEW.zip`（SHA-256 `d99284c7e6d422b16255b51d29aacb5034a1d43b254c4aca6fa389cef6caf3ae`）已進 queue，待中央 exact ACK
- C：`CDH-C03-TW-PARTNERS-EVIDENCE-001`；本機交件 `CDH_C03_001_REVIEW.zip`（SHA-256 `c500af034827fddf376419e1792b5d46d29112eea745cb9bf5a57030d5c7fd76`）已進 queue，待中央 exact ACK
- D：`CDH-D03-WEB-CONTRACT-SECURITY-001`；本機交件 `CDH_D03_WEB_001_REVIEW.zip`（SHA-256 `b9dc8e436df5a1f222c2111fb94f2b92d6d23bbff8f08492f2b16b4d76ac771b`）已進 queue，待中央 exact ACK
- E：`CDH-E03-HANDOFF-ACK-AND-CROSSLINE-INDEX-001`
- F：`CDH-F01-AFFILIATE-PROVIDER-SHELL-001`；獨立工作線已產生 `CDH_F01_001_REVIEW.zip`（SHA-256 `cb524e6bc9def5308c04bcfecb07c4be074eb0c852d71fd53a5fb877b95f9154`），待中央 exact ACK
- G：`CDH-G01-C-DRIVE-PROJECT-FILE-AUDIT-001`；獨立工作線已產生 `CDH_G01_001_REVIEW.zip`（SHA-256 `ea2a3ef3f524191f82708eb800993a37fe4fab09b7922ebea3c6b4b3754856a3`），E 未代跑 C 槽掃描，交件待中央 exact ACK

最高目標仍是「已收錄觀測價格的可靠查詢網站＋使用者主動點擊的同商品／同 variant 官方有效推薦連結」。G0 unrestricted discovery 仍 `SOURCE_BLOCKED`；官方台灣 affiliate capability 未驗證前 CTA 必須 disabled。

## 16. G01 受限 C 槽專案檔案清查（2026-11-05 Asia/Taipei）

- G01 authority：`CDH-G01-C-DRIVE-PROJECT-FILE-AUDIT-001`，只允許指定常見位置的受限盤點及經多重證據確認後的安全收攏。
- `CDH_UNIFIED_ROUND_20261105_02.zip` 已核對 SHA-256 `90d44d7c9efabd1cd09c5a05759638231be9f9318249b02274a39383c2f6e1bc`，15/15 manifest payload bytes/SHA 通過。
- C 槽頂層與 Desktop 頂層沒有名稱可辨識的 CDH 候選。Downloads 有 33 個 CDH 候選；29 個已有專案內同 SHA-256 內容，4 個為 E01/E02/N01/S01 受控跨線輸入，均維持原位。
- `LOCAL_USER_HOME\Music\University\program\比價系統` 是既有 `AI-PRICE-COMPARISON-C-DRIVE-CONSOLIDATION-488` 完成成果；3/3 `MOVED_VERIFIED` receipts 已重新通過 source absent、destination present、bytes 與 SHA 驗證。本輪未覆寫或搬動。
- 本輪外部 move/delete、release mutation、`.env` content read、network request 均為 0。G01 只完成離線檔案治理里程碑，不代表正式產品上線。
- G01 原始交件為 `review/releases/CDH_G01_001_REVIEW.zip`，SHA-256 `ea2a3ef3f524191f82708eb800993a37fe4fab09b7922ebea3c6b4b3754856a3`；同位元組副本已平放 `review/00_TO_UPLOAD`，待中央精確 ACK。

## 17. 2026-11-05 Round 04 RECEIVED ACK 與 E04 歸檔

E04 authority：`CDH-E04-UPLOAD-ACK-ARCHIVE-001`／`AUTHORIZED_LOCAL_ACK_ARCHIVE_ONLY`。下列狀態只表示中央已收到精確檔名與 SHA-256，**不表示功能驗收 PASS**：

| 工作線 | 本機 canonical filename | SHA-256 | queue archive 結果 |
|---|---|---|---|
| A | `CDH_A06_001_REVIEW.zip` | `d9fce75d876b86d5cbb28f77e8ff9354e9d38a5c9389abe10d2a2ddc46adefb5` | `ARCHIVED` |
| B | `CDH_B07_001_REVIEW.zip` | `f0a597f225233cd635e53c8646ce58ab20422250a8cb357650434eb59d342ee4` | `ARCHIVED` |
| C | `CDH_C04_001_REVIEW.zip` | `370ed70e20942693b185a540744cc5c1924502d147f7f576552703747d022ef1` | `ARCHIVED` |
| D | `CDH_D04_WEB_001_REVIEW.zip` | `c6271dafd0521bd84badcffa3819122d1ed81af8bc45a392d3f696dcc7f88acd` | `ARCHIVED` |
| E | `CDH_E03_001_REVIEW.zip` | `2f1d6516afc3821b1bda3d42d0f449b1bdf36191491a99f5d32628db841f21c1` | `ARCHIVED` |
| F | `CDH_F02_001_REVIEW.zip` | `89b4c21f9f28516052f0298b71d71c6d6f82f48daea5d91db81bcbb5815afd73` | `ARCHIVED` |
| G | `CDH_G02_001_REVIEW.zip` | `f47a6923dc4f974d55bdc2715f801bffe85a8e6992c434a59222d0aa50cd8076` | `ARCHIVED` |
| H | `CDH_H01_001_REVIEW.zip` | `01cf300af6adc66df9aa4b863592ef5f4d46f477745a764b0c340a44fa1c2214` | `ARCHIVED` |

- 歸檔批次：`review/90_UPLOADED_ARCHIVE/20261105_ROUND04_ACK/`；八份逐筆 exit `0`，receipt records `8`。
- 使用者回報 A06、E03 在 ChatGPT 上傳介面被附加 `(1)`；因未提供含空白位置的完整 alias 字串，receipt 保存中央明列的 canonical filename，不臆造 alias。移動依本機 canonical filename 與完整 SHA-256 完成。
- `review/releases` 八份原件逐檔重新雜湊，與 ACK 及 archive 副本三方一致；immutable release mutation count `0`。
- 本次未 ACK、仍留在 `review/00_TO_UPLOAD`：B06、C03、D03 Web、F01、G01。不得因版本較舊而刪除或歸檔。
- `RECEIVED ACK` 與功能裁決分離；網站上線、真實酷澎來源、台灣官方 affiliate capability、公開部署與交易仍未獲本任務核准。

### Round 04 補充 ACK

中央其後對 B06、C03、D03 Web、F01、G01 提供精確 RECEIVED ACK。E04 沿用 `20261105_ROUND04_ACK`，五份均由 queue 成功歸檔，沒有 `ALREADY_ARCHIVED`、missing、hash mismatch 或失敗：

| 工作線 | canonical filename | SHA-256 | 結果 |
|---|---|---|---|
| B | `CDH_B06_001_REVIEW.zip` | `d99284c7e6d422b16255b51d29aacb5034a1d43b254c4aca6fa389cef6caf3ae` | `ARCHIVED` |
| C | `CDH_C03_001_REVIEW.zip` | `c500af034827fddf376419e1792b5d46d29112eea745cb9bf5a57030d5c7fd76` | `ARCHIVED` |
| D | `CDH_D03_WEB_001_REVIEW.zip` | `b9dc8e436df5a1f222c2111fb94f2b92d6d23bbff8f08492f2b16b4d76ac771b` | `ARCHIVED` |
| F | `CDH_F01_001_REVIEW.zip` | `cb524e6bc9def5308c04bcfecb07c4be074eb0c852d71fd53a5fb877b95f9154` | `ARCHIVED` |
| G | `CDH_G01_001_REVIEW.zip` | `ea2a3ef3f524191f82708eb800993a37fe4fab09b7922ebea3c6b4b3754856a3` | `ARCHIVED` |

Round 04 receipt 累計 13 records；`RECEIPT_LEDGER.jsonl` 累計 20 rows；`review/00_TO_UPLOAD` 最終 `pending_count=0`。這是所有目前 queue 項目都有 exact ACK 後的結果，不是為清空資料夾而刪除。

## 18. E05 handoff 與 queue continuity

- 任務：`CDH-E05-HANDOFF-AND-QUEUE-CONTINUITY-001`；authority `LOCAL_HANDOFF_ONLY_AFTER_E04_FINISHED`。E04 已完成並保留原始 receipt／ledger／reports，E05 gate 已開啟。
- R04 authority bundle SHA-256：`ce7d509b246e7c70a957a395bcfb4c15a7c16717675f3b37868ebd6e9c68e9dc`；CRC/path/case PASS，manifest 15/15。
- 平面 enqueue 維持 staging copy → SHA/ZIP/manifest readback → atomic replace；stale partial 與 dead-owner lock 可安全恢復，活躍／不完整新 lock 不搶占。
- `archive-acks` 接受專案內 `CDH-EXACT-ACK-1` JSON。只有 exact filename/SHA 且明確 `--acknowledged` 才移動；部分失敗保留，重播為 `ALREADY_ARCHIVED`，完成移動缺 receipt 才是 recovery。
- `handoff_continuity.py` 產生 queue exact inventory、A～H role state、五分鐘接手摘要與 protected hashes；掃描範圍是明確 handoff/release/receipt allowlist，`.env` 內容讀取為 `false`。
- `RECEIVED ACK` 仍不等於功能 PASS；`SOURCE_BLOCKED`、affiliate capability `UNVERIFIED`、部署與交易禁令不變。

## 19. R05 中央收件 ACK 與 E06 歸檔（2026-11-05 Asia/Taipei）

E06 authority：`CDH-E06-RECEIPT-ACK-ARCHIVE-AND-HANDOFF-001`／`AUTHORIZED_SYNTHETIC_OFFLINE_ONLY`。輸入 `CDH_UNIFIED_CONTINUOUS_20261105_R05.zip` 已核對 SHA-256 `d0993915ff725541ca0c5053f32eddca82888082fcd1b9650f35d80c738237cd`、18 entries CRC、17/17 MANIFEST payload bytes/SHA、路徑安全與大小寫碰撞；全部通過。

中央明確 ACK 下列八份 R04 交件；ACK 只表示收件，不是功能驗收 PASS：

| 工作線 | canonical filename | SHA-256 | E06 結果 |
|---|---|---|---|
| A | `CDH_A07_001_REVIEW.zip` | `390499b3c99b2d3b551530be357f2810d6299db7c8cbd8ab182cf8ca2e19db90` | `ARCHIVED` |
| B | `CDH_B08_001_REVIEW.zip` | `a6d5ffb65860fcb33504baefd3c5288c1c75aac0494af248bb3e4c5624cd69bd` | `ARCHIVED` |
| C | `CDH_C05_001_REVIEW.zip` | `fa0a43b9b58477ac8853b1dfe0d790d6a9cfd24fbcb972fd175de07c42ac6d50` | `ARCHIVED` |
| D | `CDH_D05_WEB_001_REVIEW.zip` | `3d01788ce3e28d82e7398bf1e2f57bb77ab24ceecb815cdaa40890be486cff7a` | `ARCHIVED` |
| E | `CDH_E05_001_REVIEW.zip` | `52b3e8bfa61606cd66c9e078cbc7ebdcc174f5132d43eda92aef10668b96b61b` | `ARCHIVED` |
| F | `CDH_F03_001_REVIEW.zip` | `8a4f77e79844864d280dcffd05f6a752e4e78090763a3d5e01f13e447e6507c5` | `ARCHIVED` |
| G | `CDH_G03_001_REVIEW.zip` | `56f7c7edf5b5acd1027d6774d367ffefafa7273fb8ac801a6d3b69c84e389f6a` | `ARCHIVED` |
| H | `CDH_H02_001_REVIEW.zip` | `3d362e157c13901dc89705488b00bc31f4385c479b5c8f77b6a08ad83cc1cd08` | `ARCHIVED` |

- 批次：`review/90_UPLOADED_ARCHIVE/20261105_R05_ACK/`；8/8 exact filename/SHA、CRC 與 manifest gate 符合，`ARCHIVED=8`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。
- `review/releases` 的八份 immutable originals 逐檔與 archive 副本／ACK SHA 三方一致；release 移動、刪除、覆寫均為 0。歸檔後 queue 為空；E06 自身交件完成時會另加入 queue，須等待新的 exact ACK。
- 更新前 `MASTER_HANDOFF.md` 已保存於 `docs/HANDOFF/versions/MASTER_HANDOFF_PRE_E06_20261105.md`，兩者更新前 SHA-256 均為 `03d17e9b47befd50cda28c1c0c63070187ce57bf9bf271678c4e9ea812851463`。
- 中央獨立測試為 B08/C05/D05/E05/F03/G03/H02 合計 167/167；A07 僅有 19 份 TypeScript/TSX 轉譯診斷 0 錯誤，不得把封存測試當中央獨立執行。
- A07/B08 已重現兩個 R05 契約缺口：`price_basis=UNAVAILABLE`／null 價格應保留商品而非整頁 `INVALID_PAYLOAD`；V2 raw visible history low 與 V3 daily representative low 必須分名、不可混稱。H02 的失敗只針對舊 A06/B06，不可外推到 A07/B08。
- C05/F03 的官方台灣來源與商品級 affiliate 能力仍 `SOURCE_BLOCKED`／`UNVERIFIED`，CTA、真實擷取、正式通知、部署與交易均未授權。

## 20. R06 收件 ACK、B09 supersession 與 E07 continuity（2026-11-05 Asia/Taipei）

- 任務：`CDH-E07-ACK-AND-CONTINUITY-001`；authority `AUTHORIZED_SYNTHETIC_OFFLINE_R06_E_ONLY`。
- R06 authority ZIP SHA-256：`99707ec6058e5b9386be20a4993e94b604974b859d197fca91218202a40dfa46`；17 entries CRC PASS、16/16 Manifest payload bytes/SHA PASS、unsafe path/case collision 均為 0。
- 中央 `RECEIPT_ACK.json` 對 A08、B09-001、B09-002、C06、D06、E06、F04、G04、H03 共九份提供 exact filename/SHA/bytes ACK。九份 queue copies 均與 release originals 及 ACK 三方一致，歸檔至 `review/90_UPLOADED_ARCHIVE/20261105_R05_HANDOFF_ACK_20261105/`；`ARCHIVED=9`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。
- B09-001 `10f7ae283108b460ce533b52b75ba1698218632b38d5b58fbda8e643b9234bab` 明確記為 `RECEIVED_SUPERSEDED`／historical-only；B09-002 `35539f8d3434540c660ff51613e636c443ffc06b237806bc53f32db1e78e62e3` 記為 `RECEIVED_CANONICAL_CANDIDATE`。兩份 immutable release 都保留，E 未刪除、覆寫或自行合併。
- 收件語義 ledger：`docs/HANDOFF/R05_RECEIPT_STATUS_LEDGER.json`；技術 archive receipt 與 global `RECEIPT_LEDGER.jsonl` 仍保持原 schema，global ledger 累計 37 rows。
- 中央獨立測試：B09-002/C06/D06/E06/F04/G04/H03 合計 236/236 PASS；A08 Node/Chromium/Windows 未由中央本輪重跑。這些 scoped results 不等於公開上線或真實來源授權。
- R06 frozen coupon contract：網站主價僅可使用同商品/SKU/賣家、有效時點及使用者資格均有證據的 confirmed coupon price；券前與 confirmed 券後歷史分別保存。未知、未領、過期、不適用券不得成為主價，`null` 不得轉為 0，運費未知時 `required_total_twd=null`。
- R06 A/B 使用 V4 opt-in 增量並保留 V2/V3；C/F 官方能力仍 `SOURCE_BLOCKED`，CTA/Click URL disabled。E07 只維護 ACK、索引、handoff，不修改其他線功能原始碼。
- 更新前 master 已保存至 `docs/HANDOFF/versions/MASTER_HANDOFF_PRE_E07_20261105.md`，SHA-256 `d971f67089045fa9f8faca9d2cc754b525b676a8035ea1225a4880db17963f50`。
- E07 第一版 `CDH_E_R06_001_REVIEW.zip`（SHA-256 `95d8ab78a07b1d0657c215618cb611330866190c5f8890d6312980eae51ab401`）在獨立解壓測試發現漏放 E06 ACK fixture，結果 56 PASS / 1 ERROR；release 與 rejected evidence 均保留，queue copy 已移出待上傳收件匣。修正版使用新檔名 `CDH_E_R06_002_REVIEW.zip`，不覆寫 001。

## 21. R07 收件 ACK、E08 歸檔與封裝依賴治理（2026-11-05 Asia/Taipei）

- 任務：`CDH-E08-R06-ACK-ARCHIVE-AND-INDEX-001`；authority `SYNTHETIC_OFFLINE_LOCAL_ONLY`，僅 E handoff paths 與工具合規欄位。
- R07 authority ZIP SHA-256：`76b1332c3e2cd82a05e5f26e6d3e0c01cdf65e828f82d5b586902bdfacda2827`；21 entries CRC PASS、20/20 Manifest payload bytes/SHA PASS、unsafe path/case collision 均為 0。
- 中央對 A09、B10、C07、D07、E07 rev2、F05、G05、H04 的八份 R06 ZIP 提供 `RECEIVED_AND_INTEGRITY_PASS_ONLY` ACK。八份 queue copies 以 exact filename/SHA、CRC、Manifest gate 歸檔至 `review/90_UPLOADED_ARCHIVE/20261105_R06_HANDOFF_ACK_20261105/`；`ARCHIVED=8`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。
- 八份 `review/releases` immutable originals 均存在且 SHA 與 ACK/archive 副本一致；release mutation count `0`。歸檔後 queue 暫為空，E08 交件完成後會新增一份待 ACK 副本。
- `package_dependency_audit.py` 新增歷史 evidence 封裝 gate：測試引用的 uppercase historical evidence 必須在 ZIP 內，或由唯一 `INPUT_DEPENDENCY.json` 以 exact path/SHA 與 `NOT_RUN_INPUT_UNAVAILABLE` 具名；漏件 fail closed。
- 封裝文字稽核採 suffix allowlist，`.pyc` 等 binary 只計數、不嘗試文字解碼；`.env.example` 不自動視為秘密，但 `.env` 與其他 `.env.*` 實檔禁止封裝。
- R07 A10/B11 exact releases 尚未由 E08 收件，因此 A10/B11/G06/H05 的真跨線整合不得標 PASS，狀態保留 `NOT_RUN_INPUT_UNAVAILABLE`。
- R07 中央已重現 A09/B10 V4 wire 差異；E08 不修改 A/B/D/F/G/H 原始碼，也不以 stub 或獨立 synthetic site 冒充跨線整合。
- E08 交件入 queue 時另觀察到 `CDH_H_R07_001_REVIEW.zip`（SHA-256 `f4fcb0f73f9a59362f15f93025cb8ab489664a061916291d3c8d3077b79d4b9d`）。這是待中央 ACK 的 queue presence，不代表 H05 功能 PASS；E 未修改或開啟 H package 內容。
- E08 第一版 `CDH_E_R07_001_REVIEW.zip`（SHA-256 `677f657c00d301f30cc88cd0dec83f4a23efc8090ac7970a659944f7eed95205`）雖通過 67/67 獨立解壓測試，但稽核發現外部路徑簿含推定時間；release 與 rejected evidence 保留，queue copy 已移出。修正版以 `CDH_E_R07_002_REVIEW.zip` 交付，不覆寫 rev1。

## 22. R08／E09 R07 收件歸檔與 dependency-aware handoff（2026-11-05 Asia/Taipei）

- 任務：`CDH-E09-R07-ACK-HANDOFF-001`；輸入 R08 ZIP SHA-256 `61d75b334fd7073202691bab887186261c85d1fa42af05e79f16d1a46f24b144`，17 entries CRC PASS、16/16 Manifest payload bytes/SHA PASS、unsafe path/case collision 0。
- 中央 `RECEIPT_ACK.json` 對 B11、C08、D08、E08 rev2、F06、G06、H05 七份提供 `RECEIVED` ACK。七份 queue copies 以 exact filename/SHA 歸檔至 `review/90_UPLOADED_ARCHIVE/20261105_R07_7_WORKLINES_ACK/`；`ARCHIVED=7`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。
- 七份 `review/releases` 原始交件仍存在且 SHA 與 ACK/archive 副本一致；immutable release mutation count `0`。global receipt ledger 累計 52 rows。
- 歸檔前 queue 另有 A10 `CDH_A_R07_001_REVIEW.zip` SHA `eb4b449972f1bb6bccd9457e8ee88a2b3c69f2a2001b17fc5adfceb23c6a7e08`；本批 authority 明列 A10 `NOT_RECEIVED`，因此該副本保持原位、未歸檔、未刪除。
- B11 已由中央 scoped-verified，exact SHA `6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a`。A10 本機 presence 不等於中央 ACK；A10+B11 actual frontend/API/browser/DOM integration 仍不得由 E 宣告 PASS。
- D08 receipt 已保存，但中央 portable rerun 為 3 PASS / 4 ERROR，狀態 `RECEIVED_REWORK_REQUIRED`；receipt 不掩蓋 D09 rework gate。
- C08 仍 `SOURCE_BLOCKED`；官方台灣來源與 affiliate product-specific conversion 未驗證，CTA disabled、click URL null。
- R08 工作線狀態與 exact dependency boundary 已更新至 `WORKLINE_STATUS.md`、`TASK_STATUS_INDEX.json` 與 R07 semantic receipt ledger。
- E09 交件 `CDH_E_R08_001_REVIEW.zip` SHA-256 `da3c1c15a08604901eee5405c99df97c6abb99c456a16eab8fe29b93c3647e6c` 已進 queue；完成時 live queue 為 A10 與 E09 兩份，兩者都尚待各自的新 exact ACK。
- 最終 readback 又觀察到 `CDH_G_R08_001_REVIEW.zip` SHA-256 `9edd847686b7566889a94ffcc3837bfdcee2294f219aa60d5dde728209e78a4c`；live queue 因此為 A10、E09、G07 三份。G07 presence 不解除 A10 central-ACK dependency gate。

## 23. R09／E10 九份 R08 ACK 與版本分離治理（2026-11-05 Asia/Taipei）

- 任務：`CDH-E10-R08-NINE-ACK-HANDOFF-001`；輸入 R09 ZIP SHA-256 `be0ee2febae110a16bac12dd6c00e26c74e8006f4eb944b5fdad0d6d0a76a71b`，20 entries CRC PASS、19/19 Manifest payload bytes/SHA PASS、unsafe path/case collision 0。
- 中央對 A10 R07、A10 R08 continuation、B12、C09、D09、E09、F07、G07、H06 九份提供 `RECEIVED_ACK_ONLY_NOT_FUNCTIONAL_PASS`。九份 queue copies 以 exact filename/SHA/bytes/CRC/Manifest 歸檔至 `review/90_UPLOADED_ARCHIVE/20261105_R08_NINE_ACK/`；`ARCHIVED=9`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。
- 九份 `review/releases` 原始交件保持存在，與 ACK/archive 副本 SHA 一致；immutable release mutation count `0`。歸檔後 queue 為空，E10 交件完成後才新增自身待 ACK 副本。
- A10 R07 SHA `eb4b4499...7e08` 與 H06 歷史 browser evidence 綁定；A10 R08 continuation SHA `0cddd2f5...fccd` 是較新候選。兩者均保留、不得混稱，R07 browser pass 不可繼承至 R08。
- R08 中央獨立單線 suites B12/C09/D09/E09/F07/G07/H06 合計 198/198 PASS；此數字不重複加入各工作線的上游 replay。中央 Chromium 對 localhost 受政策阻擋，A10 R08 React suite亦因離線缺 `yallist@3.1.1` 未重跑，均不得虛報中央 browser PASS。
- D09 portable ZIP verifier 14/14 已解除前輪路徑相容性錯誤；C09 仍 `SOURCE_BLOCKED`，F07 CTA/click URL 維持 disabled/null。
- C09 既有 ZIP 的兩個 auxiliary sidecar 未列主 Manifest，記為歷史 P2 packaging limitation；舊 release 不重包、不覆寫。
- R09 工作線狀態、A10 版本分離與 exact dependency 已更新至 `WORKLINE_STATUS.md`、`TASK_STATUS_INDEX.json` 與 `R08_RECEIPT_STATUS_LEDGER.json`。
- E10 交件 `CDH_E_R09_001_REVIEW.zip` SHA-256 `d0401e584393ab1f064c988f03186788d5e03c4eb0f3f53cffb19b326c39904b` 已進 queue；完成時 queue 只有此一新 ZIP，歷史九份已收交件不需重傳。
- 最終 readback 另觀察到 `CDH_F_R09_001_REVIEW.zip` SHA-256 `75600bf4a2d8397abea93164af75e1ff99a4bab99f0082feaad859f1486ea688`；live queue 因此為 E10 與 F08 兩份，均尚待各自 exact ACK。F08 queue presence 不解除 CTA/affiliate gate。
- 後續 readback 又觀察到 `CDH_H_R09_001_REVIEW.zip` SHA-256 `d0c11a6344800b1cca1794c6cc4e83579a8aab8f2eaf7a2a2bfcb89d06f62e97`；live queue 為 E10、F08、H07 三份。H07 queue presence 不等於中央獨立新版 browser PASS。
- 最終 readback 另觀察到 `CDH_C_R09_001_REVIEW.zip` SHA-256 `28c77026e93720a01719a6c3bfc3b4250de2194ba15f288776d8a54f9eb18865`；live queue 為 C10、E10、F08、H07 四份。C10 presence 不解除 `SOURCE_BLOCKED`。

## 24. R10／E11 八份 R09 ACK 與產品裁決保存（2026-11-05 Asia/Taipei）

- 任務：`CDH-E11-R09-EIGHT-EXACT-ACK-AND-LIVE-QUEUE-001`；輸入 R10 ZIP SHA-256 `0474031243db86ffc7c7b05e7569f701f5705cf84a25b98453b987f1c99b7abc`，20 entries CRC PASS、19/19 Manifest payload bytes/SHA PASS、unsafe path/case collision 0。
- 中央對 A11/B13/C10/D10/E10/F08/G08/H07 八份提供 exact `RECEIVED_ACK`。八份 queue copies 以 canonical filename、完整 SHA-256、CRC 與 Manifest gate 歸檔至 `review/90_UPLOADED_ARCHIVE/20261105_R09_EIGHT_ACK/`；`ARCHIVED=8`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。
- 八份 `review/releases` immutable originals 均保持存在且 SHA 與 ACK/archive 副本一致；release mutation count `0`。歸檔後 queue 為空，E11 交件完成後才新增自身待 ACK 副本。
- Receipt 與產品裁決分離：A11 `PASS_SCOPED` 但 daily DOM 需新 gate；B13 `REWORK_P1_DUPLICATE_JSON_KEY`；C10 `PASS_SCOPED_SOURCE_BLOCKED`；F08 `PASS_SCOPED_CTA_DISABLED`；G08 `PASS_SCOPED_WIRE_NOT_DAILY_DOM`；H07 `EVIDENCE_PASS` 但 `PRODUCT_INTEGRATION_FAIL_DAILY_HISTORY_NOT_RENDERED`。
- R09 中央 portable suites 為 232/232；這些是上游 evidence，不由 E11 重跑或重複計數。B13 P1 及 H07 product failure 不因測試數或 ACK 被掩蓋。
- R10 固定 B11 exact SHA `6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a`。A12/G09/H08 必須用同版 A11/B11 重新證明 raw/daily、before/confirmed-after DOM；B14 必須拒絕 duplicate JSON keys。
- C10/C11 真實來源仍 `SOURCE_BLOCKED`；F08/F09 CTA/click URL 維持 disabled/null。E11 未修改其他工作線原始碼，也未使用 `.env`、Firefox、Registry、真實 DB、網路擷取、部署、affiliate click 或交易。
- E11 原始交件 `review/releases/CDH_E_R10_001_REVIEW.zip` SHA-256 `ef4489d55b69d7fc24d5965040c3e88f263847e8d2a9c64ca8a4a4055ddec70e` 已以同位元組副本平放 queue；final live queue 僅此一份，等待新的 exact ACK。

## 25. R11 A12／A13／B15 精確收件與錯置檢查（2026-11-05 Asia/Taipei）

- A12 `CDH_A_R10_001_REVIEW.zip`、A13 `CDH_A_R11_001_REVIEW.zip`、B15 `CDH_B_R11_001_REVIEW.zip` 的正式原件均已在 `review/releases`，完整 SHA-256 與中央 ACK 一致，沒有補複製、覆蓋或 release 衝突。
- 三份同位元組 queue copies 依 exact ACK 歸檔至 `review/90_UPLOADED_ARCHIVE/20261105_R11_THREE_ACK/`；`ARCHIVED=3`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。release/archive/ACK 三方雜湊一致。
- R11 派工包 `CDH_R11_FAST_TRACK_DELTA_20261105.zip` SHA-256 `8c1f71375dcf08df93f6c50cab35f7e196c641a70ca0f5b8184af3fd448b9bcb` 保持於 `input/orchestrator_bundles`，未混入 queue。
- 歸檔後 queue 留有八份未獲本次 exact ACK 的 R10 ZIP；全部保持原位，未因版本看似較舊而移動或刪除。
- 本次未建立 E 的空白 REVIEW ZIP。B15 本機 exact release 已確認，可供 D12 依自身 authority 解除輸入阻塞；E 未執行或修改 D12、A13 REV2、B15 功能碼。

## 26. R10／R11 queue 精確 ACK 整理（2026-11-05 Asia/Taipei）

- 任務 `QUEUE-ACK-R10-R11-20261105` 對 B R10、C R10 兩版、D/E/F/G/H R10 與 D12 R11 共九份提供 exact filename/SHA-256/CRC/archive-path ACK。
- 歸檔前 queue 有十份；九份 exact ACK copies 均歸檔至 `review/90_UPLOADED_ARCHIVE/20261105_QUEUE_ACK_R10_R11/`。結果：`ARCHIVED=9`、`ALREADY_ARCHIVED=0`、`MISSING=0`、`HASH_CONFLICT=0`、`FAILED=0`。
- 九份 `review/releases` 原件仍存在，release/archive/ACK 三方 SHA-256 全部一致；release mutation count `0`。歷史測試、報告與 evidence 均未刪除。
- D12 `CDH_D_R11_001_REVIEW.zip` 本機 queue 與 release 均存在且 SHA `010379c5383d91d7084bb27d8571855f4a8f7395cf4f01ad776481cc336ebcf0`，因此記為 `RECEIVED`，不是缺少。
- D12 對 B15 的安全裁決保持 `REWORK_REQUIRED_P1`；receipt 不升格 B15 功能或安全 PASS。
- 歸檔後 queue 僅剩未 ACK 的 A13 REV2 `CDH_A_R11_002_REVIEW.zip` SHA `c4a5e36f868c77682d1a4b40ad00b78611afd3d164216f8ad89827415e732405`，保持原位。
- R11 共用任務包不在 queue，未執行任務包移動；未知 ZIP 數為 0。本次未建立額外 REVIEW ZIP。

## 27. R11 REV2 A13／B15 精確收件（2026-11-06 Asia/Taipei）

- A13 REV2 `CDH_A_R11_002_REVIEW.zip` SHA `c4a5e36f868c77682d1a4b40ad00b78611afd3d164216f8ad89827415e732405` 與 B15 REV2 `CDH_B_R11_002_REVIEW.zip` SHA `48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe` 的正式原件均已在 `review/releases` 保存。
- 兩份同位元組 queue copies 依 exact RECEIVED ACK 歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_R11_REV2_TWO_ACK/`；`ARCHIVED=2`、`ALREADY_ARCHIVED=0`、`MISSING=0`、`HASH_CONFLICT=0`、`FAILED=0`。
- release/archive/ACK 三方 SHA-256 2/2 一致；release mutation count `0`，所有舊版本、失敗證據、報告與測試保持不變。歸檔後 queue 為空。
- 收件不等於功能或安全 PASS。A13 REV2 已知仍需 A 工作線修訂成 REV3 並精確接 B15 REV2；B15 REV2 安全狀態記為 `PENDING_D12_REVALIDATION`，不得以本次 ACK 取代 D12 Windows 安全複驗。
- E 本次未建立大型 REVIEW ZIP，也未修改 A、B、D 功能碼或執行其整合／安全測試。

## 28. R11 接力 A13 REV3／D12 精確收件（2026-11-06 Asia/Taipei）

- A13 REV3 `CDH_A_R11_003_REVIEW.zip` SHA `d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274`、D12 REV2 `CDH_D_R11_002_REVIEW.zip` SHA `c83174b1fac2addd959d15d29b0f28a1880bc4c371f21bca8bd88f1be87af521`、D12 補充版 `CDH_D_R11_003_REVIEW.zip` SHA `8dd8fc1ff99ab097e5578f25be4633d95a6b42b07cf76b242099b8d51637ee30` 的正式原件均在 `review/releases` 且與中央精確身分一致。
- 三份同位元組 queue copies 依 RECEIVED ACK 歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_R11_RELAY_THREE_ACK/`；`ARCHIVED=3`、`ALREADY_ARCHIVED=0`、`MISSING=0`、`HASH_CONFLICT=0`、`FAILED=0`。
- release/archive/ACK 三方 SHA-256 3/3 一致；release mutation count `0`。舊版本、失敗證據、測試與報告保持不變，歸檔後 queue 為空。
- B15 REV2 正式 release 已由前一收件批次保存；A13 REV3、B15 REV2 與 D12 evidence 的本機依賴位置已具備。此處只表示上游 artifact 可用，不代替 H09 真實 Windows 流程驗收，也不推論產品 PASS。
- E 本次未建立 REVIEW ZIP，未執行 H09，未修改其他工作線功能碼，也未接觸正式資料庫、真實 `.env`、Firefox、Registry、網路擷取、部署、分潤或交易。

## 29. H09 中央裁決與精確收件（2026-11-06 Asia/Taipei）

- H09 `CDH_H_R11_001_REVIEW.zip` SHA `d34def2c5097ffbad9ad0b304b897984fc21b42b5036e16178e050ee6423c203` 的正式 release 與 queue copy 均符合中央 exact ACK。
- queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_H09_ACK/`；`ARCHIVED=1`、`ALREADY_ARCHIVED=0`、`MISSING=0`、`HASH_CONFLICT=0`、`FAILED=0`。release/archive/ACK 三方 SHA 一致，release mutation count `0`，歸檔後 queue 為空。
- 中央 H09 裁決保存為 `PASS_SCOPED_WITH_EVIDENCE_RECONCILIATION`：18 項 evidence tests 與 SQLite 驗證已由中央重跑；原 browser harness 四個斷言錯誤已離線對帳。
- 中央沒有重新執行產品 browser journey；`product_journey_rerun=false` 必須保留，不得把離線對帳升格成重新完成真實 journey。
- 本次 receipt 不推論 A14/H10 狀態。E 未建立 REVIEW ZIP、未執行 H10，也未修改 A/H 功能碼或接觸正式資料庫與受限外部能力。

## 30. A14 精確收件與 H10 前置狀態（2026-11-06 Asia/Taipei）

- A14 `CDH_A_R11_004_REVIEW.zip` SHA `19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160` 的正式 release 與 queue copy 均符合中央 exact ACK。
- queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_A14_ACK/`；`ARCHIVED=1`、`ALREADY_ARCHIVED=0`、`MISSING=0`、`HASH_CONFLICT=0`、`FAILED=0`。release/archive/ACK 三方 SHA 一致，release mutation count `0`，歸檔後 queue 為空。
- B15 REV2 exact release 已由前批保存；A14＋B15 REV2 的 artifact 前置位置已具備，可由 H 工作線依 H10 authority 進行真正 Windows E2E。
- 本次 receipt 不推論 H10 已執行或 A14 功能 PASS。E 未建立 REVIEW ZIP、未執行 H10，也未修改 A/H/B 功能碼或接觸正式資料庫與受限外部能力。

## 31. H10 第一版收件與失敗狀態保存（2026-11-06 Asia/Taipei）

- H10 第一份正式交件 `CDH_H_R11_002_REVIEW.zip` SHA `bdfe4ba6671400a6479213c53b8d1f7d4f1a20c75a8b393c170795baa2d36257` 的 release 與 queue copy 均符合中央 exact ACK。
- queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_H10_REV1_ACK/`；`ARCHIVED=1`、`ALREADY_ARCHIVED=0`、`MISSING=0`、`HASH_CONFLICT=0`、`FAILED=0`。release/archive/ACK 三方 SHA 一致，release mutation count `0`，歸檔後 queue 為空。
- 中央已確認 H10 ZIP 的 Manifest／CRC／基本語法 `21/21 PASS`；但實際產品 E2E 保持 `FAIL_HEALTHCHECK_UNREACHABLE_CHROME_NOT_STARTED`，Chrome 未啟動。
- RECEIVED ACK 與封裝完整性不得掩蓋產品 E2E FAIL。後續 G 診斷、必要的 A14 修訂與 H10 修訂版都必須保留第一版失敗證據，不得覆寫。
- E 本次未建立 REVIEW ZIP、未執行診斷或 E2E、未修改 G/A/H 功能碼，也未接觸正式資料庫或受限外部能力。

## 32. REVIEW／STATUS_ONLY 永久平面交件規則（2026-11-06 Asia/Taipei）

- 使用者只需一次上傳 `review/00_TO_UPLOAD` 內全部 ZIP。所有正式原件永久保存在 `review/releases`，中央 exact filename/SHA-256 ACK 後才移動 queue 副本至 `review/90_UPLOADED_ARCHIVE`。
- 有程式變更使用 `*_REVIEW.zip`。沒有程式變更但完成正式診斷、確認阻塞或重要狀態變更時使用 `*_STATUS_ONLY.zip`；不得以無意義重複掃描持續產生狀態包。
- STATUS_ONLY 在 ZIP 根目錄或唯一單層 artifact 目錄強制同層包含 `STATUS.json`、`SUMMARY.md`、`MANIFEST.json`，不得有模糊的多組 roots。STATUS 必須具名 task ID、A～H 工作線、狀態、時間與前置依賴；SUMMARY 必須列執行結果、未完成項目、中央處理需求、下一步及等待條件；Manifest 必須宣告除自己外的全部成員及 SHA-256。
- `flat_queue.py` 已將 REVIEW 與 STATUS_ONLY 區分為 `artifact_type=release|status_only`，兩者共同執行 canonical filename、CRC、路徑、symlink、secret、nested ZIP、Manifest payload、immutable release、flat enqueue 與 exact ACK gate。
- `handoff_continuity.py` 接受 STATUS_ONLY 作為角色預期交件。Windows usage 與 upload SOP 已更新；新增 STATUS_ONLY 正向、缺必備檔案、未宣告成員與 continuity 回歸。
- 首次回歸因 staging `.partial` 檔名被誤拿來判斷 artifact type，造成 25 個既有 enqueue errors；已修正為依已驗證的 immutable source name 選擇 staging 內容 validator，沒有放寬 canonical queue filename gate。修正後 targeted 37/37、完整 handoff 78/78 PASS。
- 本次規則更新產生一次小型 E STATUS_ONLY 交件；不重包歷史資料。後續只有新的正式狀態變更才再產生狀態包。

### STATUS_ONLY 相容性修訂

- 第一份 E status snapshot `CDH_E_R11_001_STATUS_ONLY.zip` 在根目錄契約完成後產生，內容記錄 targeted 37/37 與 full 78/78；原件及未 ACK queue copy 保留、不覆寫。
- 隨後 queue 出現 G10 的合法單一頂層 artifact 目錄格式。因使用者只要求 ZIP「包含」必備檔案，E 將 validator 修訂為接受根目錄或唯一單層 artifact root，仍要求三檔同層、唯一 root、Manifest 全覆蓋及所有既有安全 gate。
- 時間欄位正規化接受 `generated_at`／`created_at`／`created_at_utc`／`timestamp_utc`；前置依賴接受 `prerequisites`／`dependencies`，必要語意仍不得缺失。
- H 工作線在最終 readback 新增兩份 `created_at_utc` STATUS_ONLY；加入該明確 UTC alias 回歸後 targeted 39/39、完整 handoff 80/80 PASS。live queue 六份均通過 filename/CRC/Manifest/path/type gate。
- H 的兩份 package 各有一個隔離 SQLite evidence path，故 sensitive gate 記為 `PRESENT_ALLOWED_FOR_EXACT_ACK_ONLY`；E 未讀取資料庫內容、未移動或刪除，等待中央逐份審查及 exact ACK。
- `CDH_E_R11_003_STATUS_ONLY.zip` SHA-256 `b4d69993a5da86e4cd39d7511d5cfd7aacc61bbd90765118f675fdb5e7389abd` 是最新 E 狀態候選；release 與 queue 副本同位元組。001／002 標記為 `SUPERSEDED_LOCAL_STATUS_SNAPSHOT`，未獲 ACK 前全部保持原位。

## 33. H10／E19 六份 STATUS_ONLY 精確收件（2026-11-06 Asia/Taipei）

- 任務 `QUEUE-ACK-H10-SIX-20261106` 收到 E19 001／002／003、G10 診斷及 H10 REV2 003／004 共六份 exact filename/SHA-256 RECEIVED ACK；收件不代表功能驗收 PASS。
- 六份 queue copies 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_H10_STATUS_SIX_ACK/`；`ARCHIVED=6`、`ALREADY_ARCHIVED=0`、`MISSING=0`、`HASH_CONFLICT=0`、`FAILED=0`、`RECOVERED=0`。
- 六份 `review/releases` immutable originals 全部仍存在，release/archive/ACK SHA-256 6/6 一致；release mutation count `0`。RECEIPT_LEDGER 由 89 增至 95 rows，歸檔後 queue 為空。
- 版本裁決：E19-003 是最新治理基準，E19-001／002 為保留舊版；H10-004 是最新 REV2 狀態，H10-003 為保留舊版；G10 維持 `ENVIRONMENT_LIMITATION`；H10 REV2 維持 `FAIL_BROWSER_ASSERTION_FORMAT_MISMATCH`。
- H10 003／004 各含一個隔離合成 SQLite evidence path。本次中央只對這兩個 exact ZIP 授權收件歸檔，原 `PRESENT_ALLOWED_FOR_EXACT_ACK_ONLY` advisory 永久保留；不構成未來封裝真實私人資料庫的通用授權。
- E 未執行或修改 H10 REV3，未建立新的 STATUS_ONLY／REVIEW ZIP，亦未接觸正式資料庫、真實 `.env`、Firefox、Registry、未授權擷取、部署、分潤或交易。

## 34. H10 REV3 精確收件（2026-11-06 Asia/Taipei）

- 中央對 H10 REV3 `CDH_H_R11_005_REVIEW.zip` SHA-256 `7cba1e0e6031a9f8abb0a13326cfe7d493602adb41b4b5514df07a13153c9ac4` 提供 exact RECEIVED ACK，中央裁決為 `PASS_SCOPED`。
- 正式 release 與 queue copy 的 filename/SHA-256 完全一致；CRC、Manifest、路徑及 nested ZIP gate 通過。queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_H10_REV3_ACK/`；`ARCHIVED=1`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。
- `review/releases/CDH_H_R11_005_REVIEW.zip` immutable original 保持存在，與 archive/ACK SHA 三方一致；release mutation count `0`。RECEIPT_LEDGER 由 95 增至 96 rows。
- H10 REV3 package 有一個隔離合成 SQLite evidence path，原 advisory 保留為 `PRESENT_ALLOWED_FOR_EXACT_ACK_ONLY`。本次只授權此 exact ZIP 的收件，不構成未來封裝真實私人資料庫的通用授權。
- H10 REV1 的健康檢查／Chrome 未啟動 FAIL 與 REV2 的文字格式斷言 FAIL 均保持原 release、archive、報告及 evidence，不被 REV3 覆蓋。
- E 未修改或執行 A15、B16、D13、H11，也未建立同義 STATUS_ONLY；其後續前置與驗收狀態由各自工作線及中央另行裁決。

## 35. A15 checkpoint／B16 正式後端精確收件與 legacy STATUS ACK 相容性（2026-11-06 Asia/Taipei）

- 中央對 A15 checkpoint `CDH_A_R11_005_STATUS_ONLY.zip` SHA `48861846f750a95db75d8ef0e4f80613c2f13794b3cfb2e7ba2a957e79b91e4b` 與 B16 `CDH_B_R12_001_REVIEW.zip` SHA `d2149952fe1693381f74ac639a770b393b8703a368df68eea990cd5e231cf23b` 提供 exact RECEIVED ACK。
- A15 裁決保持 `UI_PREWORK_READY_NOT_API_INTEGRATED`；B16 為 `PASS_SCOPED`；A15＋B16 完整網站 E2E 仍是 `NOT_RUN`。Receipt 不改變這些產品狀態。
- A15 checkpoint 使用三檔 STATUS_ONLY 契約建立前的 `reports/A15/STATUS.json`、`TEST_RESULTS.md`、`SHA256_MANIFEST.json` 版型。嚴格 queue list 正確 fail closed；E 修正 archive-only 分支，使其只有在 exact filename/SHA ACK 下才可按一般 release 驗證 CRC、路徑及既有 17 筆 manifest 後歸檔。新 enqueue/list 規則未放寬。
- 相容性修正首次回歸為 `3 failures + 1 error`，原因是錯把既有 `require_manifest=False` list 行為當成 exact-ACK 授權；改成獨立 `allow_legacy_status_only_exact_ack` 旗標後 targeted 40/40、完整 handoff 81/81 PASS。
- 兩份 queue copies 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_A15_B16_ACK/`；`ARCHIVED=2`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。兩份 immutable releases 保持存在，release/archive/ACK SHA 2/2 一致，ledger 由 96 增至 98 rows。
- E 未修改 A/B 功能碼、未執行 A15 真 API 整合、D13 或 H11。相容性修正屬 E 工具實質變更，依永久規則交付最小 E22 REVIEW，不建立同義 STATUS_ONLY。
- E22 原始交件 `CDH_E_R12_001_REVIEW.zip` SHA-256 `9d36039b04797ac9ac7a19eaccabfc00cad028ebd27a9ba8d5d25f23521c9e4d` 已保存於 `review/releases`，同位元組副本已進 `review/00_TO_UPLOAD` 等待中央 exact ACK。

## 36. R12 三份候選精確收件與候選／正式操作分離（2026-11-06 Asia/Taipei）

- 中央對 A15 `CDH_A_R12_001_REVIEW.zip` SHA `5cc44dedd910ff9b2055cfc2772ad0c3d6db627ffc818794f81fd3d9b5552d4b`、D13 `CDH_D_R12_001_REVIEW.zip` SHA `eeb7b434db360818399414133cdb9e173654ea6850ea0a76ac702a626f806d2f`、E22 `CDH_E_R12_001_REVIEW.zip` SHA `9d36039b04797ac9ac7a19eaccabfc00cad028ebd27a9ba8d5d25f23521c9e4d` 提供 exact RECEIVED ACK。
- 三份 queue copies 已作為不可信、不可執行候選歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_R12_CANDIDATE_THREE_ACK/`；`ARCHIVED=3`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。三份 releases 保持存在，release/archive/ACK SHA 3/3 一致，ledger 由 98 增至 101 rows。
- A15 正式整合候選記為已收件；A15 package 含兩份 hash-bound 上游 ZIP，nested advisory 保留。收件不等於 A15＋B16 完整網站 E2E 已執行。
- D13 已發現 B16 one-time preview/confirm token 並行競態：兩個請求可收到 201／200，但資料庫只有一筆。D13 package 含一份 B16 上游 ZIP及三個 synthetic security-evidence paths，nested/sensitive advisories 保留；不得執行其中腳本或載入 SQLite。
- E22 legacy STATUS exact-ACK 相容性成果已收件；E22 receipt 不構成部署或正式資料修改授權。
- 候選收件與正式操作正式分離：exact ACK 可授權 byte-identical 候選移入隔離 archive，但不能推論功能 PASS、執行權、正式資料寫入、部署、分潤或交易權。正式操作仍須各自功能／安全 gate 與 authority。
- E 未修改 B16、執行 D13 複驗或 H11，未解壓／執行候選，也未建立純歸檔 STATUS_ONLY。

## 37. B16 REV2 精確收件與 D13／H11 接力狀態（2026-11-06 Asia/Taipei）

- 中央對 B16 REV2 `CDH_B_R12_002_REVIEW.zip` SHA-256 `6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6` 提供 exact RECEIVED ACK。
- ZIP CRC、54 筆 Manifest、路徑與 SHA gate 通過；無 nested ZIP。四個因檔名含 token 而觸發 sensitive-path advisory 的項目均為 D13／B16 REV2 security repro evidence/tool 路徑，候選未執行。
- queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_B16_REV2_ACK/`；`ARCHIVED=1`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。immutable release 保持存在，release/archive/ACK SHA 一致，ledger 由 101 增至 102 rows。
- 中央 B16 REV2 結果保存：B16／B15 portable tests 54/54；並行確認為 201＋409 且僅一個 writer；失敗 token 不得重用；新 preview 冪等語意保留；API route/request format 未變。
- D13 正式安全複驗與 H11 Windows Chrome E2E 均保持 `NOT_RUN`。B16 REV2 RECEIVED／portable PASS 不得推論整體安全准入或發布就緒。
- E 未修改或執行 B16、D13、H11，未執行候選內 repro 工具，未建立純歸檔 STATUS_ONLY。

## 38. D13 REV2／H11 精確收件與 R12 定點修復 gate（2026-11-06 Asia/Taipei）

- 中央對 D13 REV2 `CDH_D_R12_002_REVIEW.zip` SHA `dc72821516e2d7a726f8bfa72976db19f560621b75fb31d8d0440bc2a1bf256c` 與 H11 `CDH_H_R12_001_REVIEW.zip` SHA `70b35c8a0c757a5a7288b272dd228d7c9053a0849a5e5bf9e4d00c2dcb603c07` 提供 exact RECEIVED ACK。
- 兩份 queue copies 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_D13_REV2_H11_ACK/`；`ARCHIVED=2`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。immutable releases 均保持存在，release/archive/ACK SHA 2/2 一致，ledger 由 102 增至 104 rows。
- D13 REV2 安全裁決維持 `FAIL`。原並行 token 競態已修復，但新缺陷 `D13-B16-REV2-001`：首次建立私人 SQLite 時，交易中途失敗可能留下缺 schema 的空白 DB，令新 batch-preview 回 `400 PRIVATE_STORE_REJECTED`。
- D13 candidate 含兩份 hash-bound 上游 ZIP及六個 token security repro evidence/tool 路徑；只作不可執行候選收件，nested/sensitive advisories 保留，未執行工具或載入資料庫。
- H11 為 `PASS_SCOPED`，保存 Windows Chrome 15/15 產品流程證據；但 A15 原版 `preview_server.py` 固定綁 B16 REV1，H11 使用測試專屬載入器切至 REV2，因此正式原版啟動器仍是 `NOT_CONFIRMED`。
- H11 candidate 含一份隔離合成 SQLite evidence；exact-ACK advisory 保留。H11 PASS 不可直接繼承至未來 A15 REV2＋B16 REV3，亦不代表正式發布就緒。
- E 未修改 B/A/D/H 程式碼，未執行安全複驗或 Chrome E2E，未建立純歸檔 STATUS_ONLY。

## 39. B16 REV3 精確收件與後續綁定／安全 gate（2026-11-06 Asia/Taipei）

- 中央對 B16 REV3 `CDH_B_R12_003_REVIEW.zip` SHA-256 `f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7` 提供 exact RECEIVED ACK；此為收件，不是部署核准。
- ZIP CRC、51 筆 Manifest、路徑、nested ZIP 與 sensitive-content gate 全部 PASS。queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_B16_REV3_ACK/`；`ARCHIVED=1`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。
- immutable release 保持存在，release/archive/ACK SHA 一致；ledger 由 104 增至 105 rows。B16 REV1／REV2 與 D13 舊 FAIL evidence 全部保留。
- 中央 B16 REV3 證據：核心 28/28、B15 回歸 28/28；D13 首次交易故障反例重跑 PASS；失敗後 schema 完整、部分 observation／commit_audit 為 0；失敗 token 不可重用；新 preview／confirm 可恢復；API route/request format 未變。
- `A15_REV2_BINDING`、`D13_REV3_REVALIDATION`、`H11_FORMAL_LAUNCHER_E2E` 均維持 `NOT_RUN`。B16 REV3 receipt／portable PASS 不推論上述 gate 已通過或正式發布就緒。
- E 未修改或執行 A、B、D、H 程式碼與測試，未建立純歸檔 STATUS_ONLY。

## 40. A15 REV2／D13 REV3 精確收件與 H11 最終前置（2026-11-06 Asia/Taipei）

- 中央對 A15 REV2 `CDH_A_R12_002_REVIEW.zip` SHA `be0becbaa384e1a633c5893b266dbbb03c449ca405ef1f0c07bb8dd53456634b` 與 D13 REV3 `CDH_D_R12_003_REVIEW.zip` SHA `8aef750caa17c894159d13705f9962e4f6e856ef3ced1658ddb951523b241e54` 提供 exact RECEIVED ACK。
- 兩份 ZIP 均通過 CRC、Manifest、路徑與 exact SHA gate；各含兩份 hash-bound upstream ZIP，nested advisory 保留，未開啟 nested payload。
- queue copies 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_A15_REV2_D13_REV3_ACK/`；`ARCHIVED=2`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。immutable releases 保持存在，release/archive/ACK SHA 2/2 一致，ledger 由 105 增至 107 rows。
- 中央 portable tests 79/79 PASS；D13 的 token 競態與首次 SQLite 交易失敗兩項既有缺陷均通過限定複驗；A15 REV2 已精確綁定 B16 REV3。
- H11 正式啟動器最終 Chrome 補驗仍為 `NOT_RUN`。A15／D13 RECEIVED 與 portable PASS 不可取代 H11 真實 Windows browser、HTTP、DOM、SQLite 證據，也不代表正式發布就緒。
- E 未修改或執行 A、D、H 程式碼與測試，未建立純歸檔 STATUS_ONLY。

## 41. H11 最終版精確收件與本機 MVP 前置完成（2026-11-06 Asia/Taipei）

- 中央對 H11 最終版 `CDH_H_R12_002_REVIEW.zip` SHA-256 `725232938d0f9111b0546b02a9e34a7a86015ebe1205452656e8fd586f365f1e` 提供 exact RECEIVED ACK，裁決為 `PASS_SCOPED`。
- ZIP CRC、46 筆 Manifest、路徑及 exact SHA gate PASS；無 nested ZIP。一份隔離合成 SQLite evidence 觸發 sensitive advisory，只依 exact ACK 作不可執行候選收件，E 未載入其內容。
- queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_H11_FINAL_ACK/`；`ARCHIVED=1`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。immutable release 保持存在，release/archive/ACK SHA 一致，ledger 由 107 增至 108 rows。
- H11 證據：Windows Chrome 15/15、中央 evidence tests 14/14、final checks 17/17，且中央已驗證隔離 SQLite。正式基準為 A15 REV2 SHA `be0becbaa384e1a633c5893b266dbbb03c449ca405ef1f0c07bb8dd53456634b`、B16 REV3 SHA `f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7`、D13 REV3 SHA `8aef750caa17c894159d13705f9962e4f6e856ef3ced1658ddb951523b241e54`。
- H11 先前健康檢查／Chrome FAIL、文字格式 FAIL、測試專屬載入器 checkpoint 與全部證據均保留，不被最終版覆寫。
- 下一階段 A16 是 Windows 本機 MVP 首次使用體驗；H12 只驗證 A16 新增／受影響部分。H11 PASS_SCOPED 不構成公開部署或正式分潤授權。
- E 未修改或執行 A16／H12，未建立純歸檔 STATUS_ONLY。

## 42. A16 Windows 本機 MVP 精確收件與 H12 前置（2026-11-06 Asia/Taipei）

- 中央對 A16 `CDH_A_R12_003_REVIEW.zip` SHA-256 `3c6d329cebdda9f8d269f3740952f897b6c95e932d0e04fef4a625defe0fc37e` 提供 exact RECEIVED ACK，裁決為 `PASS_SCOPED`。
- ZIP CRC、117 筆 Manifest、路徑與 exact SHA gate PASS；含 A15 REV2／B16 REV3 兩份 hash-bound upstream ZIP，nested advisory 保留，E 未開啟 nested payload。
- queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_A16_ACK/`；`ARCHIVED=1`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。immutable release 保持存在，release/archive/ACK SHA 一致，ledger 由 108 增至 109 rows。
- 中央已驗證 117/117 Manifest、22/22 Python tests 與必要 Node script syntax；Windows Chrome 首次使用目前是 A16 作者提供的 PASS evidence。
- H12 乾淨隔離 Windows 首次使用驗收仍為 `NOT_RUN`，必須使用正式 `Start-CDH-MVP.cmd`／`Status-CDH-MVP.cmd`，不得以作者專用載入器取代。A16 不得視為獨立安裝程式。
- E 未修改或執行 A16／H12，未建立純歸檔 STATUS_ONLY；A16 receipt 不構成公開部署、系統服務安裝、Registry 修改或正式分潤授權。

## 43. H12 REV1 有效失敗報告精確收件（2026-11-06 Asia/Taipei）

- 中央對 H12 REV1 `CDH_H_R12_003_REVIEW.zip` SHA-256 `42c73c6e7a59f802946bb34cbd6809431fc6da13d46d94a7673bd3aa29aef865` 提供 exact RECEIVED ACK；裁決為 `VALID_FAILURE_REPORT / A16_REWORK_REQUIRED`。
- ZIP CRC、30 筆 Manifest、路徑、nested ZIP、sensitive-content 與 exact SHA gate 全部 PASS。queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_H12_REV1_FAIL_ACK/`；`ARCHIVED=1`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。
- immutable release 保持存在，release/archive/ACK SHA 一致，ledger 由 109 增至 110 rows。H12 REV1 failure evidence 與所有歷史版本永久保留。
- 中央 evidence tests 10/10 PASS，但產品 Chrome E2E 未啟動，產品狀態不得升格。受測 A16 SHA 為 `3c6d329cebdda9f8d269f3740952f897b6c95e932d0e04fef4a625defe0fc37e`。
- 缺陷 `A16-H12-001`：首次使用文件／預檢漏列 B16 間接依賴；缺陷 `A16-H12-002`：根目錄 Windows CMD 換行／命令執行格式錯誤。A16 REV2 與後續 H12 重驗仍待執行。
- E 未修改或執行 A16／H12，未建立純歸檔 STATUS_ONLY；RECEIVED ACK 不掩蓋 FAIL 或構成部署授權。

## 44. A16 REV2 精確收件與 H12 REV2 前置（2026-11-06 Asia/Taipei）

- 中央對 A16 REV2 `CDH_A_R12_004_REVIEW.zip` SHA-256 `8eba2b5059c92fcd71897ee345527c78741ebe6c3230c45eab87dd4921b339e4` 提供 exact RECEIVED ACK，裁決為 `PASS_SCOPED`。
- ZIP CRC、53 筆 Manifest、路徑與 exact SHA gate PASS；含 A16 REV1 與 H12 REV1 兩份 hash-bound upstream ZIP，nested advisory 保留，E 未開啟 nested payload。
- queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_A16_REV2_ACK/`；`ARCHIVED=1`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。immutable release 保持存在，release/archive/ACK SHA 一致，ledger 由 110 增至 111 rows。
- 中央已驗證 53/53 Manifest、24/24 Python tests、完整依賴 8/8 與根目錄 CMD CRLF 3/3。H12 REV1 FAIL 與兩項原始缺陷證據保持不變。
- H12 REV2 真正乾淨 Windows 首次使用驗收仍為 `NOT_RUN`，必須驗證根目錄 CMD、Chrome、HTTP、SQLite、重啟持久性、缺依賴、連接埠占用及安全停止。
- E 未修改或執行 A16／H12，未建立純歸檔 STATUS_ONLY；A16 REV2 receipt 不構成獨立 Windows 首次使用 PASS 或公開部署授權。

## 45. H12 REV2 16/17 失敗報告精確收件（2026-11-06 Asia/Taipei）

- 中央對 H12 REV2 `CDH_H_R12_004_REVIEW.zip` SHA-256 `df490f54ff4315e2c4171248464040e02ce2eef58265d1e5c3f88e4854294b80` 提供 exact RECEIVED ACK；產品狀態維持 `FAIL_16_OF_17`。
- ZIP CRC、45 筆 Manifest、路徑與 exact SHA gate PASS；無 nested ZIP。兩份隔離合成 SQLite evidence 觸發 sensitive advisory，只依 exact ACK 作不可執行候選收件，E 未載入內容。
- queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_H12_REV2_FAIL_ACK/`；`ARCHIVED=1`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。immutable release 保持存在，release/archive/ACK SHA 一致，ledger 由 111 增至 112 rows。
- 唯一失敗條件為 `first_use_controls_and_classification`。原始 Chrome exit code 必須保持失敗，不得以後續離線推算或補驗改寫。
- H12 REV3 只允許修正 H 測試工具的載入等待與分潤按鈕判定，使用精確 A16 REV2／B16 REV3 補跑受影響條件；按鈕不存在、逾時、啟用或出現不可信可操作連結皆須 FAIL。
- 若 REV3 只執行針對性補驗，必須明確組合先前 16 項證據，不得聲稱同一次完整 browser run 17/17 PASS。H12 REV1／REV2 FAIL 全部保留。
- E 未修改或執行 H 測試工具、A16、B16 或正式資料庫，未建立純歸檔 STATUS_ONLY。

## 46. H12 REV3 組合證據精確收件與 A17／H13 接力（2026-11-06 Asia/Taipei）

- 中央對 H12 REV3 `CDH_H_R12_005_REVIEW.zip` SHA-256 `1d0b58a9a5973dc410de159504971ffc17ca537c9cffba7216d24b8da8d9da9a` 提供 exact RECEIVED ACK，裁決為 `PASS_SCOPED_COMPOSITE_EVIDENCE`。
- ZIP CRC、20 筆 Manifest、路徑、nested ZIP、sensitive-content 與 exact SHA gate 全部 PASS。queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_H12_REV3_ACK/`；`ARCHIVED=1`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。
- immutable release 保持存在，release/archive/ACK SHA 一致，ledger 由 112 增至 113 rows。H12 REV1／REV2 原始 FAIL 與 REV3 補驗資料全部保留。
- 正式 evidence binding：A16 REV2 SHA `8eba2b5059c92fcd71897ee345527c78741ebe6c3230c45eab87dd4921b339e4`、B16 REV3 SHA `f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7`、H12 REV2 SHA `df490f54ff4315e2c4171248464040e02ce2eef58265d1e5c3f88e4854294b80`。
- `PASS_SCOPED_COMPOSITE_EVIDENCE` 是先前 16 項 evidence 加 REV3 受影響條件補驗的組合裁決，不代表同一次完整 browser 17/17 run；REV2 原始 Chrome FAIL exit code 不得改寫。
- A17 本機試用版尚未執行；H13 維持 `WAITING_FOR_A17`。H12 結案不構成公開部署、正式分潤、自動擷取或系統安裝授權。
- E 未修改或執行 A17／H13，未建立純歸檔 STATUS_ONLY。

## 48. E23 GitHub 安全同步盤點（2026-11-07 Asia/Taipei）

- E23 任務 `CDH-E23-GITHUB-REPOSITORY-CONSOLIDATION-20261106` 授權建立公開 GitHub 交接入口與逐檔安全篩選。指定儲存庫為 `ZhenyangZent/KuPeng_Price_Comparison_System`；遠端初始盤點為 `PUBLIC`、`main` 尚無 commit、帳號 `ADMIN`。遠端身分仍須在 push 前重新核對。
- 本機根目錄開始時不是 Git repository；為避免碰觸 H13 工作目錄，在專案內獨立建立同步候選。`docs/HANDOFF/PROJECT_FILE_INDEX.csv` 是完整本機位置清單，`GITHUB_UPLOAD_INVENTORY.csv` 是發布分流；兩者不能以 ACK 替代機密審查。
- A17 正式中央裁決維持 `PASS_SCOPED`，SHA `5de6b85e72767e8135b7ff0e6e3acb534965d5f636f61eea918cb082b02a8237`，E34 已完成 exact ACK 歸檔。本機出現 H13 候選失敗報告 `FAIL_H_TEST_STALE_RESULT_RACE`；尚無中央最終裁決，H13 不得列為 PASS，亦不得推論 A17 產品程式有缺陷。
- 原始 release、歷史失敗證據、私人 SQLite、正式 `.env`、憑證與未審查巢狀 ZIP 均留在本機，不因 GitHub 同步移動或刪除。初始 GitHub 鏡像不等於公開部署或具真實酷澎／分潤操作權限。

## 47. A17 Windows 本機試用版精確收件與 H13 前置（2026-11-06 Asia/Taipei）

- 中央對 A17 `CDH_A_R13_001_REVIEW.zip` SHA-256 `5de6b85e72767e8135b7ff0e6e3acb534965d5f636f61eea918cb082b02a8237` 提供 exact RECEIVED ACK，裁決為 `PASS_SCOPED`。
- ZIP CRC、91 筆 Manifest、路徑與 exact SHA gate PASS；包含六份 immutable baseline ZIP 與四份 B11 synthetic coupon SQLite fixtures，nested/sensitive advisories 保留。E 未開啟 nested ZIP 或載入 fixture。
- queue copy 已歸檔至 `review/90_UPLOADED_ARCHIVE/20261106_A17_ACK/`；`ARCHIVED=1`、`FAILED=0`、`ALREADY_ARCHIVED=0`、`RECOVERED=0`。immutable release 保持存在，release/archive/ACK SHA 一致，ledger 由 113 增至 114 rows。
- 中央已驗證 91/91 delivery Manifest、58/58 Runtime Manifest、7/7 A17 Python tests、52/52 上游封裝程式／正式版本一致，以及隔離 Python service 啟動、API、停止 PASS。
- Windows CMD／Chrome 與真正首次試用仍為 `NOT_RUN_H13_REQUIRED`。H13 必須證明乾淨隔離工作區只需 A17 整合包與文件所述 Python 環境，不需自行尋找八份歷史 ZIP。
- A17 receipt／portable PASS 不構成 Windows 首次試用 PASS、獨立安裝程式、公開部署、正式分潤或自動擷取授權。
- E 未修改或執行 A17／H13，未建立純歸檔 STATUS_ONLY。
