# F01 Affiliate Provider Shell

這是台灣 Coupang Partners 的純離線、fail-closed 後端介面。它讀取呼叫者明確指定的 C02 本機契約檔，不讀專案根目錄 `.env`、不建立 HTTP client、不呼叫 Coupang、不產生或開啟連結，也不提供一般商品 URL fallback。

目前 production state 固定由 `PROVIDER_CONTRACT_V1.json` 驗證為：

- `market=TW`
- `state=PENDING_OFFICIAL_DOCS`
- `click_url=null`
- `verified_product_match=false`
- `cta_enabled=false`

`policy.validate_candidate()` 是純函式離線 evaluator，供未來取得獨立 authority 後驗證 exact product／variant／seller、官方 output host、期限與撤銷、繁中揭露、證據與帳號資格。validator 通過本身不會改變 F01 production state。

本機測試：

```powershell
python -m unittest discover -s tests/web/affiliate_provider -v
```

`.env.example` 只有無效佔位值與未啟用的設定名稱，不會被 runtime 自動載入。
