# S01 操作許可清單

AUTHORITY: `AUTHORIZED_DOCUMENTED_SOURCE_FEASIBILITY_AND_LOCAL_USER_INPUT_ONLY`

## 可立即執行

- 讀取使用者明確指定的本機 UTF-8 `.csv`。
- 讀取使用者明確貼上的文字，或由 CLI 指定的本機 UTF-8 文字檔。
- 只在本機解析、驗證、正規化 URL 字串；不得 DNS lookup、HTTP、redirect 或 browser open。
- 輸出全新的 clue JSON；已存在的輸出拒絕覆蓋。
- 人工閱讀公開政策／開發文件／正式公告並記錄 URL、日期、版本與限制。
- 產生授權申請草稿，但不寄送。

## 需要新的獨立授權

- 使用任何真實 API token、feed、export 或排程輪詢。
- 以 Coupang Partners、Threads、飛比 BI 或第三方資料作自動 discovery。
- 把任何 discovery clue 接入 C01 quote、decision、outbox 或通知。
- 讀取個人資料請求所得檔案並轉成正式歷史或資格證據。
- 建立跨線介面或修改 C01、D01、D02、D03、A／B／N／E 工作線。

## 永久或本輪禁止

- Coupang 商品／搜尋／登入／訂單／結帳頁自動擷取。
- 未記載 API、逆向端點、Firefox 日常 Profile／Cookie、Registry。
- 真通知、領券、購物車、下單、付款。
- 把 `UNKNOWN` 填成 0、免運、有貨、符合 WOW 或目前可用優惠。
- 把公開可見、robots、低頻、登入狀態或使用者貼 URL 當作上游授權。

## Gate

在書面來源授權與獨立 qualification 證據設計都通過前：

SOURCE_STATUS: `SOURCE_BLOCKED`

REAL_DISCOVERY_ADAPTER_COUNT: `0`

REAL_QUALIFICATION_ADAPTER_COUNT: `0`
