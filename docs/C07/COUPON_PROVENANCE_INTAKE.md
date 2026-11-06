# 優惠券價格 provenance 入庫規格

## 目的

只把「有來源、同商品身分、同時間窗、同資格 profile」的券後價列為已確認主價；其餘券只保留拒絕原因或 `possible` 提示，不污染已確認歷史。

## 必要欄位

- 完整 `series_identity`：平台、商品、SKU、賣家、品況、包裝／數量簽章。
- `observed_at`、可信 base price、TWD、單一展示單位及 base source evidence。
- coupon ID、狀態、折抵額、單件／整筆口徑、最低數量、有效期間。
- eligibility profile 與證據狀態；WOW、首購、私人券不可默認為一般訪客適用。
- coupon scope identity 與 scope evidence。
- `already_included_in_base`；若為 true，必須另附券前比較價及其來源，禁止二次扣券。
- shipping 必須分為 `KNOWN` 或 `UNKNOWN`；未知時 `required_total_twd=null`。
- C06 六類 evidence 與五項獨立 rights；分潤 URL 權利不授權價格、保存或展示。

## 狀態

- `TEST_ONLY_CONFIRMED`：僅合成契約 fixture 可使用，不代表真實券。
- `REVIEW_READY_CONFIRMED`：脫敏證據通過政策形狀，仍待中央，不是 runtime authority。
- `SOURCE_BLOCKED`、`CLAIM_REQUIRED`、`UNVERIFIED`、`INELIGIBLE`、`EXPIRED`：不得作確認券後主價。
- `NO_COUPON`：主價回退可信 base price。

## 歷史

`BEFORE_COUPON` 與 `CONFIRMED_AFTER_COUPON` 是兩個獨立 observation。兩者都保留相同商品身分、觀測時間與來源；券後序列另保留 coupon ID、資格 profile 與 scope evidence。過去曾有效不表示現在有效。

## 執行

單筆 record：`python -m research.coupon_evidence_c07.cli <record.json> --now <ISO-time>`。

合成案例：`python -m research.coupon_evidence_c07.cli research/coupon_evidence_c07/SYNTHETIC_PROVENANCE_FIXTURES.json --case T01_CONFIRMED_99_MINUS_50 --now 2026-11-05T12:00:00Z`。
