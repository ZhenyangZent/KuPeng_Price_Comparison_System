# 脫敏最小能力證據規格

Schema：`CDH-C06-SANITIZED-CAPABILITY-EVIDENCE-1`

## 允許欄位

- evidence ID、fixture class、市場、issuer 名稱與已核對狀態。
- program scope、文件 SHA-256／bytes／版本／有效期。
- 六類 evidence class、API 操作名稱、精確商品匹配狀態。
- 撤銷／展示／保存條款是否已文件化。
- 五項彼此獨立的 rights state 與文件段落定位。
- admission state 與中央審核狀態。

## 一律排除

- 文件全文或截圖。
- 姓名、信箱、電話、會員／帳號識別碼。
- API key、secret、Token、Cookie、Authorization header。
- 真實 endpoint request、click URL、轉址結果。

## 固定安全值

每個 intake capsule 固定：`central_approval=PENDING`、`runtime_authorized=false`、`automatic_promotion=false`、`cta_enabled=false`、`click_url=null`。中央後續若要授權 runtime，必須建立另一份獨立 authority，不可直接修改 intake 結果。
