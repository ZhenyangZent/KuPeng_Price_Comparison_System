# S01 離線 USER_PROVIDED_CLUE Adapter

## 用途

`apps/s01` 把使用者明確選擇的 CSV 或貼上文字轉為可追溯 clue JSON。它不開啟任何 URL，不呼叫 API，不讀取 Firefox，不匯入 C01，也不發通知。

## CSV 欄位

UTF-8 CSV 必須含 `clue_text`，可選欄位如下：

- `source_url`：HTTPS 參考來源；只驗證字串，不開啟。
- `product_url`：只接受 `tw.coupang.com`／`www.tw.coupang.com` 的 `/products/` 或 `/vp/products/` 直接路徑；追蹤參數會移除。
- `claimed_at`：含時區的 ISO-8601；是聲稱時間，不是 adapter 驗證時間。
- `claim_price_minor`：非負整數 TWD minor units；例如 `100` 代表 NT$1。仍只是未驗證聲稱。
- `claim_context`：`UNSPECIFIED`、`HISTORICAL`、`CURRENT_CLAIM`、`PROMOTION` 或 `FIRST_PURCHASE_PROMOTION`。

未知欄位、重複欄名、非 UTF-8、超過 1 MiB、超過 1000 筆、無時區時間或不安全 URL 均 fail closed。

## 執行

```powershell
python -m apps.s01 --csv experiments\S01\fixtures\manual_clues.csv --observed-at 2026-11-04T12:00:00+08:00 --output experiments\S01\manual_clues_output.json
```

貼上文字：

```powershell
python -m apps.s01 --text "使用者人工看到的候選；尚未驗證" --output experiments\S01\pasted_clue_output.json
```

CLI 只寫入不存在的新檔；如輸出已存在會回傳 exit code `2`，不覆蓋。

## 輸出邊界

每筆 clue 固定包含：

- `clue_class=USER_PROVIDED_CLUE`
- `automated_source_status=SOURCE_BLOCKED`
- `upstream_permission_status=NOT_PROVEN`
- qualification 全部 `UNKNOWN`
- `qualification_status=UNQUALIFIED_CLUE_ONLY`
- `notification_eligible=false`
- `c01_event_created=false`
- `links_fetched=0`

含首購、新用戶、`1 元` 或 `$1` 的文字會被標記，但不會解析成現在價格或資格。
