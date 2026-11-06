# F05 Coupon-bound Affiliate Gate

F05 是離線 candidate composer。它讀取已解析的 `CDH-COUPON-PRICE-V4` 合成快照、F04 trust decision 與 C06 runtime ceiling，分別決定展示價與 CTA：coupon 狀態只能影響價格，不能增加導購權限。

目前 C06 為 `SOURCE_BLOCKED`，因此即使合成券已確認且展示價為 49，最終仍固定 `click_url=null`、CTA disabled。所有測試網址使用 `.invalid`，程式沒有 HTTP client、`.env` loader、瀏覽器或購物行為。
