# C10 privacy 與負向案例

C10 遞迴拒絕 password、token、cookie、authorization、private key、credential、session 等欄位，以及 Bearer、private-key header、userinfo URL 型態。`contains_credentials` 或 `contains_personal_data` 為 true、未確認 redaction，都整筆拒絕。

負向 fixtures 包含：expired/revoked evidence、SKU 不符、coupon 過期或未知、source SHA 不符、synthetic 冒充 licensed、超期保存、未確認刪除、raw payload persistence、link disclosure、私人資訊、錯誤 source-class binding 與 weakened C09 decision。
