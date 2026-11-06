# CDH-LOCAL-HISTORY-1 JSON

FORMAT_VERSION: `CDH-LOCAL-HISTORY-1`

CALCULATION_VERSION: `history-v3.0-c01-r04.5-compatible-exploratory-d04-v1`

TIMEZONE: `Asia/Taipei`

JSON 以 UTF-8、sorted keys、禁止 NaN 輸出。`export_sha256` 是加入該欄位前 canonical JSON 的 SHA-256；落地檔案另有 byte SHA-256。

數值價格單位為整數 TWD。無合理樣本時為 `null`，不得填 0。真正觀測到 0 時保留 0，並加入 `ZERO_PRICE_UNVERIFIED_TOTAL`。

窗口為 `[as_of_taipei_date - N days, as_of_taipei_date)`，不含當日。相同 UTC 小時只取首個有效樣本；每天與各窗口都採精確整數 median floor。

所有 series 都必須帶完整品質旗標；消費端不得只讀 `historical_low_twd` 而忽略 `identity_state`、`is_comparable`、`comparison_status`、`window_day_counts` 與 `quality_flags`。
