# A／B／D 使用 C07 合成 fixtures 的方式

SOURCE: `research/coupon_evidence_c07/SYNTHETIC_PROVENANCE_FIXTURES.json`

RESULT_INDEX: `research/coupon_evidence_c07/SYNTHETIC_STATUS_RESULTS.json`

- A 可用 expected display／confirmed／possible 值驗證主價與文案，但必須保留 `TEST_ONLY` 標示。
- B 可把每個完整 record 當 V4 adapter 的合成輸入，驗證雙歷史、quantity、shipping 與 null/zero。
- D 可使用 error cases 驗證 secret、二次折抵與 zero-clamp 防線。
- 不得把 fixtures 的 `SYN-*` identity、`111...` 文件 SHA 或 `TEST_ONLY_CONFIRMED` 當真實資料。
- T11 只固定舊 V2 raw low `10` 與 V3 daily representative low `20` 必須分離；C07 不改 V2/V3 原始碼。
