# F02 Affiliate Binding V2

這是獨立、純函式、唯讀的 B06 V2 × C03 × F01 binding layer；不修改或 import 已交付模組，不讀 `.env`、不建立 HTTP client、不開啟 URL。

Production 入口先用 explicit local paths 載入 frozen C03/F01 contract，再將其 snapshot 與嚴格解析的 B06 nested Affiliate DTO 傳入 `AffiliateBindingV2.bind()`。目前受控資料必定得到 `SOURCE_AUTHORIZATION_REQUIRED`、`click_url=null`、`verified_product_match=false`、`bound_product_id=null`、`ui_cta_state=DISABLED`。

完整允許路徑只在 `.invalid` 合成測試驗證純函式；不代表台灣官方能力已取得。

測試：

```powershell
python -m unittest discover -s tests/web/affiliate_binding_v2 -v
```

詳見 `F02_V2_BINDING_CONTRACT.md`。
