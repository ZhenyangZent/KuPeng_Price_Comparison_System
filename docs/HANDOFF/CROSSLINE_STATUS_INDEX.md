# Coupang Deal Hunter｜Crossline status index

UPDATED_LOCAL_DATE: `2026-11-05`

## R10 / E11

- A11/B13/C10/D10/E10/F08/G08/H07 八份 exact ACK queue copies 已歸檔；`RECEIVED_ACK` 不等於功能或產品 PASS。
- B13 保持 `REWORK_P1_DUPLICATE_JSON_KEY`；H07 保持 `EVIDENCE_PASS`／`PRODUCT_INTEGRATION_FAIL_DAILY_HISTORY_NOT_RENDERED`。
- A12/G09/H08 需要同版 daily DOM 新證據；C source blocked、F CTA disabled、公開部署與交易仍未授權。

## R09 / E10

- A10 R07、A10 R08 continuation、B12/C09/D09/E09/F07/G07/H06 九份 exact ACK queue copies 已歸檔；receipt 不等於 integration/deployment authority。
- H06 舊 evidence 僅綁 A10 R07；A10 R08 必須由 G08/H07 使用 exact SHA 新驗證，不可沿用舊 browser pass。
- D09 portable rework central 14/14；C source blocked、F CTA disabled；正式 DB write、live source、deployment 仍未授權。

## R08 / E09

- B11/C08/D08/E08 rev2/F06/G06/H05 exact ACK queue copies 已歸檔；`RECEIVED` 不等於 general feature PASS。
- A10 local ZIP 已觀察但本批中央明列 `NOT_RECEIVED`，仍在 queue；A10+B11 真 browser integration 不得宣告 PASS。
- D08 為 `RECEIVED_REWORK_REQUIRED`；C source 仍 blocked；B11 exact SHA 可作 R08 dependency。

## R07 / E08

- R06 八份 exact ACK queue copies 已歸檔；ACK level 僅 `RECEIVED_AND_INTEGRITY_PASS_ONLY`，不是功能 PASS。
- R07 A10/B11 exact releases 尚未收件；A10/B11/G06/H05 真實跨線 gate 為 `NOT_RUN_INPUT_UNAVAILABLE`。
- E08 只新增 handoff/package governance；未修改其他工作線功能碼。

## Accepted baselines

- A05 `66652edfd641869ac63ea44c0254e712441fceccd77ea3bb78f706120cb14d0e`：synthetic frontend preview evidence；integration pending。
- B05 `31ab7903f56dfc4fc339d6b04aea74eebb1fea257a4e69554202cafc4c8c953e`：read-only copied-SQLite API；not production DB service。
- C02 `8aed0aea0f962db9a140cea2c87c7127f9645d1821ee7ef4545fec2a670ab8da`：research contract；Taiwan provider capability unverified。
- D02 Web `fe9fb15143b472ac58c48104d059aea8f9184bee22e83104044be422d48fe100`：security harness；cross-package allowlist correction pending。
- D04 `0bd8d8a449257dfdb056e324033280f84c2c06479f8475553b6854cd31aaa2f3`：offline historical analysis limited PASS。
- E02 `19735c499c6645509a1834560f154c51dbc103143955380d4508a25a64c6ce7b`：flat queue/handoff limited PASS。

## Active assignments

| Role | Task | Ownership | Gate/notes |
|---|---|---|---|
| A | `CDH-WEB-A06-FRONTEND-API-INTEGRATION-001` | `apps/price-web/frontend/**` | locally submitted `CDH_A06_001_REVIEW.zip`; pending exact ACK |
| B | `CDH-WEB-B06-PRICE-QUERY-CONTRACT-001` | `services/price_query/**` | locally submitted `CDH_B06_001_REVIEW.zip`; pending exact ACK |
| C | `CDH-C03-TW-PARTNERS-EVIDENCE-001` | `research/affiliate/**` | locally submitted `CDH_C03_001_REVIEW.zip`; pending exact ACK |
| D | `CDH-D03-WEB-CONTRACT-SECURITY-001` | `tools/web_security/**` | locally submitted `CDH_D03_WEB_001_REVIEW.zip`; pending exact ACK |
| E | `CDH-E03-HANDOFF-ACK-AND-CROSSLINE-INDEX-001` | handoff paths | ACK/archive/index only |
| F | `CDH-F01-AFFILIATE-PROVIDER-SHELL-001` | `services/affiliate_provider/**` | locally submitted `CDH_F01_001_REVIEW.zip`; pending exact ACK |
| G | `CDH-G01-C-DRIVE-PROJECT-FILE-AUDIT-001` | `reports/G01/**` | locally submitted `CDH_G01_001_REVIEW.zip`; pending exact ACK |

## Frozen gaps before integration

`data_classification`, detail source fields, affiliate DTO shape, variant search, `item_condition`, provider host/product/variant verification, loopback proxy/port and strict placeholder scanning remain unresolved across A/B/D/F. Real Coupang fetch, real affiliate conversion, GitHub deployment, notifications and transactions remain unauthorized.

## Round 04 received acknowledgements

`RECEIVED_ACK` only; no functional PASS was granted.

| Role | Received artifact | SHA-256 | Remaining unacknowledged queue artifact |
|---|---|---|---|
| A | `CDH_A06_001_REVIEW.zip` | `d9fce75d876b86d5cbb28f77e8ff9354e9d38a5c9389abe10d2a2ddc46adefb5` | none |
| B | `CDH_B07_001_REVIEW.zip`; supplement `CDH_B06_001_REVIEW.zip` | `f0a597f225233cd635e53c8646ce58ab20422250a8cb357650434eb59d342ee4`; `d99284c7e6d422b16255b51d29aacb5034a1d43b254c4aca6fa389cef6caf3ae` | none |
| C | `CDH_C04_001_REVIEW.zip`; supplement `CDH_C03_001_REVIEW.zip` | `370ed70e20942693b185a540744cc5c1924502d147f7f576552703747d022ef1`; `c500af034827fddf376419e1792b5d46d29112eea745cb9bf5a57030d5c7fd76` | none |
| D | `CDH_D04_WEB_001_REVIEW.zip`; supplement `CDH_D03_WEB_001_REVIEW.zip` | `c6271dafd0521bd84badcffa3819122d1ed81af8bc45a392d3f696dcc7f88acd`; `b9dc8e436df5a1f222c2111fb94f2b92d6d23bbff8f08492f2b16b4d76ac771b` | none |
| E | `CDH_E03_001_REVIEW.zip` | `2f1d6516afc3821b1bda3d42d0f449b1bdf36191491a99f5d32628db841f21c1` | none |
| F | `CDH_F02_001_REVIEW.zip`; supplement `CDH_F01_001_REVIEW.zip` | `89b4c21f9f28516052f0298b71d71c6d6f82f48daea5d91db81bcbb5815afd73`; `cb524e6bc9def5308c04bcfecb07c4be074eb0c852d71fd53a5fb877b95f9154` | none |
| G | `CDH_G02_001_REVIEW.zip`; supplement `CDH_G01_001_REVIEW.zip` | `f47a6923dc4f974d55bdc2715f801bffe85a8e6992c434a59222d0aa50cd8076`; `ea2a3ef3f524191f82708eb800993a37fe4fab09b7922ebea3c6b4b3754856a3` | none |
| H | `CDH_H01_001_REVIEW.zip` | `01cf300af6adc66df9aa4b863592ef5f4d46f477745a764b0c340a44fa1c2214` | none |

## Continuous R04

R04 已授權 A07/B08/C05/D05/E05/F03/G03/H02 各自在隔離白名單持續開發。E05 為 `READY_FOR_REVIEW`；其他角色在 E05 snapshot 時若未見 release/queue，只能標 `AUTHORIZED_NOT_OBSERVED`，不能推論未執行或 PASS。即時狀態以 `LATEST_HANDOFF_STATUS.json` 為準。

## R05 received ACK and new assignments

R04 的 A07、B08、C05、D05 Web、E05、F03、G03、H02 已由中央提供 exact filename/SHA ACK，E06 全部歸檔至 `20261105_R05_ACK`。此狀態是 `RECEIVED_ACK_NOT_FUNCTIONAL_PASS`；原始 releases 全部保留。

| Role | R05 task | State at E06 handoff | Product gate |
|---|---|---|---|
| A | `CDH-A08-UNAVAILABLE-AND-HISTORY-SEMANTICS-001` | `PENDING_UPLOAD` — `CDH_A08_001_REVIEW.zip` / `5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d` | exact ACK not yet received |
| B | `CDH-B09-V2-HISTORY-SEMANTICS-AND-READMODEL-001` | `PENDING_UPLOAD_MULTIPLE_UNACKNOWLEDGED` — B09 `_001` / `10f7ae283108b460ce533b52b75ba1698218632b38d5b58fbda8e643b9234bab`; `_002` / `35539f8d3434540c660ff51613e636c443ffc06b237806bc53f32db1e78e62e3` | central must identify exact artifact(s); E does not choose or delete revisions |
| C | `CDH-C06-TW-PARTNERS-ONBOARDING-EVIDENCE-001` | `PENDING_UPLOAD` — `CDH_C06_001_REVIEW.zip` / `48c79370e21bcf9a09cab3d6374f9488820b7ff80d40288bd7dd49da6969b783` | `SOURCE_BLOCKED`; exact ACK not yet received |
| D | `CDH-D06-WEB-INTEGRATION-SECURITY-GATES-001` | `AUTHORIZED_NOT_OBSERVED` | independent A08/B09 validation only |
| E | `CDH-E06-RECEIPT-ACK-ARCHIVE-AND-HANDOFF-001` | `READY_FOR_REVIEW` | local ACK/archive/handoff only |
| F | `CDH-F04-AFFILIATE-TRUST-ENVELOPE-001` | `PENDING_UPLOAD` — `CDH_F04_001_REVIEW.zip` / `7ab8faaff936d38d246e2e838ed11e239665be60c5a015e0e76f477ec418067d` | exact ACK not yet received; CTA remains disabled |
| G | `CDH-G04-CURRENT-RELEASES-CI-PREFLIGHT-001` | `PENDING_UPLOAD` — `CDH_G04_001_REVIEW.zip` / `403c88c9d8f2491c4393d44a2b72c04cfd2ea5163e1be361c6a3cec52d2b7a7d` | exact ACK not yet received |
| H | `CDH-H03-A07-B08-INTEGRATION-JOURNEY-001` | `AUTHORIZED_NOT_OBSERVED` | synthetic fixture; H02 old-scope failure not inherited |

Canonical R05 decision: V2 `last_observed_price_twd=null` with `price_basis=UNAVAILABLE` is valid and fail-closed; V2 `observation_period_min_twd` is the visible valid raw history minimum, while V3 `period_low_twd` remains the completed-day daily representative minimum. No real provider, deployment or transaction authority was granted.

## R06 receipt and coupon-history milestone

R05 的九份交件已依 `RECEIPT_ACK.json` exact filename/SHA 歸檔；這是 receipt integrity，不是 deployment authority。B09-001 保留為 `RECEIVED_SUPERSEDED`，B09-002 是後續 canonical candidate。

| Role | R06 task | E07 handoff state | Gate |
|---|---|---|---|
| A | `CDH-A09-COUPON-FIRST-UI-001` | `AUTHORIZED_NOT_OBSERVED` | V4 opt-in coupon-first UI; preserve V2/V3 |
| B | `CDH-B10-COUPON-PRICE-READMODEL-001` | `AUTHORIZED_NOT_OBSERVED` | confirmed coupon and dual-history read model |
| C | `CDH-C07-POLICY-COUPON-EVIDENCE-001` | `AUTHORIZED_NOT_OBSERVED` | official evidence only; `SOURCE_BLOCKED` |
| D | `CDH-D07-COUPON-AND-HEADER-SECURITY-001` | `AUTHORIZED_NOT_OBSERVED` | independent negative/security validation |
| E | `CDH-E07-ACK-AND-CONTINUITY-001` | `REVISION_2_READY_FOR_REVIEW` | `_001` local package rejected after independent test; `_002` is upload candidate |
| F | `CDH-F05-COUPON-BOUND-AFFILIATE-GATE-001` | `AUTHORIZED_NOT_OBSERVED` | CTA remains disabled without official evidence |
| G | `CDH-G05-V4-CI-PREFLIGHT-001` | `AUTHORIZED_NOT_OBSERVED` | V4 CI/preflight only |
| H | `CDH-H04-V4-SITE-JOURNEY-001` | `AUTHORIZED_NOT_OBSERVED` | synthetic/offline journey only |

Coupon contract gate: only `CONFIRMED_APPLICABLE` evidence may drive the displayed coupon price; unclaimed, expired, ineligible or unknown coupons remain non-primary. `history.before_coupon` and `history.confirmed_after_coupon` are separate observations; zero and unknown remain distinct.

