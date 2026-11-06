# F03 Affiliate Gateway V3

F03 是純本機、預設停用的 gateway stub。它嚴格解析 B06 `CDH-WEB-CONTRACT-V2` nested Affiliate envelope、唯讀載入 C04 readiness，只有 authority、account、credential、六項 runtime capability、exact identity、host/path、TTL/revocation、disclosure 與 user intent 全部成立時才呼叫 provider adapter。

目前 frozen C04 狀態為 `SOURCE_AUTHORIZATION_REQUIRED`，因此 gateway 不會呼叫 adapter，輸出固定 `click_url=null`、CTA disabled。程式沒有真實 Coupang endpoint、HTTP client、`.env` loader、browser 或交易函式。

測試：

```powershell
python -m unittest discover -s tests/affiliate_gateway_v3 -v
```

`.env.example` 只有 inert placeholders；正式秘密載入不屬於本輪 authority。
