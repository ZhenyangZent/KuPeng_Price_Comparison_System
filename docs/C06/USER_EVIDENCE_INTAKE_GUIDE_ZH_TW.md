# 台灣 Coupang Partners 官方證據離線入庫指南

## 目的

此流程只把使用者主動提供、已脫敏的官方文件整理成中央可審查的最小證據膠囊。它不登入平台、不連線驗證帳號、不呼叫 API，也不產生或點擊分潤連結。

## 可接受輸入

1. 官方條款、技術說明或帳號資格頁面的 PDF、HTML 快照或純文字匯出。
2. 文件必須能辨識市場、發行者、版本、生效日、有效期限及適用的 Partners 方案。
3. 帳號資格證據只保留「資格存在／期限／方案範圍」；姓名、信箱、會員編號、密鑰、Cookie、Token 與完整帳號畫面必須先遮蔽。
4. 文件需由使用者明確放入新的隔離 intake 目錄；不得指向 `.env`、Firefox Profile、資料庫、Registry 匯出或日常下載快取。

## 六類證據

- `concept`：只說明方案或歸因概念，不能證明 API、帳號或 runtime 能力。
- `source`：證明文件由台灣官方 Partners 範圍發行。
- `technical`：列出可用操作、輸入輸出、host、錯誤、限制與版本。
- `account`：證明特定帳號具備資格；只能提交脫敏證明。
- `runtime`：另行核發、可撤銷的執行授權；不可由技術文件自動推得。
- `data_retention_rights`：價格、歷史、圖片、衍生資料的保存與展示權。

## 入庫步驟

1. 複製 `EVIDENCE_RECORD.schema.json` 所描述的欄位，建立 `EVIDENCE_RECORD.json`。
2. 將已脫敏文件與 JSON 放在同一隔離目錄，使用相對 POSIX 路徑。
3. 計算文件 SHA-256 與 byte count；不要只靠檔名或 URL 判定身分。
4. 執行：`python -m research.affiliate_readiness_c06.cli <record.json> --base-dir <intake-dir>`。
5. 退出碼 `0` 只表示格式與 byte identity 可送審，不表示功能已獲授權。
6. 將輸出的最小 capsule、原文件 SHA-256 與人工核對結果送交中央；原文件內容不進前端、不進日誌。

## 中央複查

中央必須逐一確認 issuer、市場、方案範圍、有效期限、API scope、精確商品匹配、撤銷、展示與保存條款。任何一項未知都維持 fail-closed。`REVIEW_READY` 不等於 `RUNTIME_AUTHORIZED`。

## 禁止事項

不得提交密鑰、Cookie、Token、會員編號、個資、真實 click URL 或 `.env`。不得用 Seller Center、韓國 Partners 或一般商品網址替代台灣 Partners 技術授權。
