# Handoff next actions

1. 上傳 `review/00_TO_UPLOAD` 內目前所有 ZIP；收件匣維持平面結構，可一次全選，中央逐檔以完整檔名與 SHA-256 ACK。
2. 中央 Orchestrator 對每個實際收到的檔案回報完整檔名與 SHA-256；`RECEIVED` 與功能 `PASS` 分開裁決。
3. 新任務取得精確 ACK 後，才對相符 queue 副本執行 `flat_queue.py archive`。禁止整夾清空或移動 `review/releases`。
4. 新工作線 release 完成時可隨時 `enqueue`，不必等待其他工作線，也不建立會阻塞後續交件的預先 batch。
5. E02 不核准 GitHub push、公開部署、真實酷澎來源、自動通知、Firefox Profile、Registry 變更或交易；這些需要各自獨立 authority。

## 2026-11-05 Round 02

1. A06/B06/D03 先凍結 search/detail/affiliate DTO、classification、variant query、item condition 與 loopback same-origin 契約，再做本機 synthetic E2E。
2. C03 只用官方可核驗文檔確認台灣 Partners／deep-link 能力；無證據時保持 `PENDING_OFFICIAL_DOCS`。
3. F01 建立 offline provider shell 與 disabled-by-default adapter，不讀真 `.env`、不發真轉換請求；需獨立新 Codex。
4. G01 僅做受限 C 槽 dry-run audit；需獨立新 Codex，E 不代跑或移動檔案。
5. 本輪六份已 ACK 副本已歸檔；E03 執行期間 A06、B06、C03、D03、F01、G01 已各自加入 queue。E03 完成後 queue 應另含 `CDH_E03_001_REVIEW.zip`，共七份；均不得在未取得各自 exact ACK 前歸檔。
6. G01 已完成受限唯讀 audit，0 新搬移；中央 Orchestrator 應先核對 `CDH_G01_001_REVIEW.zip` 精確 SHA，再決定是否 ACK。清理 Downloads、擴大掃描或改動既有外部收攏根需新的獨立 authority。

## 2026-11-05 Round 04

1. A06、B07、C04、D04 Web、E03、F02、G02、H01 的 queue 副本已依 exact ACK 歸檔；這只是 `RECEIVED_ACK`，不是功能 PASS。
2. Queue 尚有 B06、C03、D03 Web、F01、G01；中央若已收到，須另給各自完整 filename 與 SHA-256，否則保持原位。
3. 不得用 Round 04 ACK 回溯替代舊版 B06/C03/D03/F01/G01 的 ACK，也不得為清空資料夾刪除它們。
4. 補充 exact ACK 已於後續收到；B06、C03、D03 Web、F01、G01 均成功歸檔，queue 現為空。未來新 ZIP 仍須逐檔另取 exact ACK，不得套用本輪 authority。

## Continuous R04 / E05

1. 使用 `handoff_continuity.py --write` 重建 `FIVE_MINUTE_STATUS.md`、最新 queue／role state 與 protected hashes；不讀 `.env`。
2. 各工作線 R04 release 可獨立 enqueue，毋須等待其他線；使用者可 Ctrl+A 上傳當時 queue 全部 ZIP。
3. 中央回 exact ACK 時可用 `archive-acks` 匯入；部分 mismatch 保留，重播不得重複 ledger。
4. E05 只處理 handoff continuity；不解除來源、affiliate、部署或交易 gate。

## R05 / E06

1. A07、B08、C05、D05 Web、E05、F03、G03、H02 的 exact ACK queue copies 已歸檔；不得再次上傳或用此 ACK 處理新檔。
2. 上傳 E06 與其後各線新產生的平面 queue ZIP；中央須逐份回 canonical filename 與完整 SHA-256。未 ACK 檔案不得移動。
3. A08/B09 依中央 frozen contract 修正 unavailable/null 與 raw-history/daily-representative semantics；D06/G04/H03 只能獨立驗證，不得改 A/B。
4. C06/F04 未取得官方台灣能力與商品級綁定證據前，維持 `SOURCE_BLOCKED`、affiliate CTA disabled；不得以一般商品 URL 冒充追蹤連結。
5. E06 不核准 GitHub push、公開部署、日常 Firefox、Registry、`.env`、正式 DB、真實通知、擷取或交易；任何後續 archive 仍需新的 exact ACK authority。

## R06 / E07

1. A08、B09-001、B09-002、C06、D06、E06、F04、G04、H03 已依 exact ACK 歸檔；B09-001 只作 historical superseded evidence，B09-002 才是 canonical candidate。兩者 release 都不得刪除。
2. 上傳 R06 新交件時維持平面 queue；中央須逐份提供新 filename/SHA ACK。不可將本批 ACK 套用到 A/B/C/D/E/F/G/H 的 R06 ZIP。
3. A09/B10 必須以 V4 opt-in 實作 confirmed coupon price 與券前/券後雙歷史，V2/V3 不得破壞；D07/G05/H04 獨立驗證，不修改 A/B。
4. C07/F05 沒有官方台灣 runtime、帳號資格與 exact product identity 證據前，維持 `SOURCE_BLOCKED`、CTA disabled。
5. E07 不授權 `.env`、正式 DB、Firefox、Registry、網路擷取、公開部署、真實通知、領券或交易。

## R07 / E08

1. rev1 已因 inferred timestamp 記錄 rejected；只上傳 `review/00_TO_UPLOAD/CDH_E_R07_002_REVIEW.zip`，中央回 canonical filename 與完整 SHA-256 後才能歸檔該副本。
2. A10/B11 exact releases 未到齊前，G06/H05 真跨線測試保持 `NOT_RUN_INPUT_UNAVAILABLE`；不得用 stub 宣告整合 PASS。
3. 新 review ZIP 的測試若引用歷史 evidence，必須封裝該 evidence 或提供 exact `INPUT_DEPENDENCY.json` 並具名 `NOT_RUN_INPUT_UNAVAILABLE`。
4. `.pyc` 等 binary 不作文字 secret scan；`.env.example` 僅可作 placeholder template，實際 `.env` 永久禁止封裝。
5. 新 ACK 不得套用本批 R06 ACK；仍需逐檔 exact filename/SHA authority。

## R08 / E09

1. 保留 queue 中 A10，不得使用 R07 七份 ACK 歸檔；中央須另回 A10 exact filename/SHA ACK。
2. 上傳 E09 release 後逐檔回 exact ACK；E09 自身 queue copy 未確認前不得移動。
3. A10 central ACK 與 exact dependency gate 完成前，G07/H06 actual A10+B11 browser integration 維持 `NOT_RUN_INPUT_UNAVAILABLE`。
4. D09 修復 portable ZIP member separator 相容性時不得放寬 traversal、case collision 或 manifest hash gate。
5. C09/F07 不得解除來源或 affiliate gate；真實 CTA、click URL、抓取、部署與交易仍禁止。

## R09 / E10

1. 上傳 E10 與其他新 R09 releases；中央須逐份回 canonical filename 與完整 SHA-256，未 ACK 副本不得歸檔。
2. G08/H07 只能以 A10 R08 `0cddd2f5...fccd` + B11 exact SHA 建立新版 evidence；不得沿用 A10 R07 browser pass。
3. A11 提供 Windows 本機安全啟停；不得改真實 `.env`、Firefox、Registry 或對外綁定。
4. B13/C10 只處理 synthetic/manual dry-run preview；正式 B11 DB write 與真實來源自動批准維持 0。
5. F08 未取得官方台灣 product-specific affiliate evidence 前，CTA 與 click URL 必須 fail closed。

## R10 / E11

1. A11/B13/C10/D10/E10/F08/G08/H07 八份 queue copies 已依 exact ACK 歸檔；不得再次套用本批 ACK 到任何新 release。
2. 上傳 E11 與後續 R10 平面 queue ZIP；中央須逐份回 canonical filename 與完整 SHA-256，未 ACK 副本不得歸檔。
3. B14 必須在 JSON ingress 拒絕 duplicate keys；不得靠 last-wins、預設來源拒絕或 0 DB writes 冒充修復。
4. A12/G09/H08 必須用 exact same-version A11/B11 證明 raw/daily、before/confirmed-after DOM；H07 舊 product failure 不得覆蓋。
5. C11 維持 `SOURCE_BLOCKED`，F09 維持 CTA disabled/null；真實來源、affiliate click、部署與交易仍需獨立 authority。


