# CDH Affiliate Capability Evidence V2

本契約提供 F 工作線唯讀匯入使用，並非 Coupang 官方 schema。每一項能力各自持有狀態與 evidence，不存在可一次開啟全部功能的 `provider_verified`。

允許的升級鏈只有：

`UNKNOWN -> CANDIDATE -> DOCUMENTARY_VERIFIED -> ACCOUNT_AUTHORIZED -> RUNTIME_VERIFIED`

`REJECTED`、`REVOKED`、`EXPIRED` 是吸收式關閉狀態。升級到 `DOCUMENTARY_VERIFIED` 必須有 Coupang 台灣官方來源、`market=TW`、文件版本、生效日及只對該能力的明確支持；帳號資格與 runtime 驗證需要新的獨立 authority。

目前只有 `membership_program` 與 `link_attribution_concept` 達到文件層級驗證，而且都不能直接開啟 runtime。所有連結產生、認證、exact identity、host、撤銷、資料權利、揭露、rate limit 與技術支援能力維持 `UNKNOWN`。

連結能力與商品資料權利互不傳遞。即使未來成功產生分潤連結，也不能反向解鎖商品搜尋、圖片再展示、快取或歷史價格衍生。

契約永遠不得包含 API key、Cookie、Authorization header、帳號識別碼或其他秘密。
