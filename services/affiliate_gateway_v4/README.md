# F04 Affiliate Trust Envelope

此模組只提供離線 candidate：後端注入式 HMAC key、exact product/SKU/seller/original URL hash、expiry、revocation event/readback、disclosure、evidence IDs、nonce/replay guard 與 redacted audit。

目前 C05 authority 為 `SOURCE_AUTHORIZATION_REQUIRED`，所以 gateway 在讀取 envelope 前即 fail closed：`click_url=null`、`cta_enabled=false`、allowlist 空。`CONTRACT_FIXTURE_TEST_ONLY` 即使簽章正確也只會得到 `CONTRACT_FIXTURE_VERIFIED_NONCLICKABLE`，永遠不產生對外 CTA。

模組沒有 endpoint、HTTP client、瀏覽器、自動 `.env` loader 或交易行為。`.env.example` 僅為 inert placeholder。

測試：

```powershell
python -m unittest discover -s tests/affiliate_gateway_v4 -v
```
