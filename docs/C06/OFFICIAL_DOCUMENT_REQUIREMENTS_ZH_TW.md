# 台灣 Partners 正式文件需求清單

## 必要身分

- 市場明確為台灣 `TW`。
- 發行者可驗證為 Coupang 官方，且方案範圍明確為 Taiwan Partners，不是 Seller Wing 或其他市場。
- 文件有可雜湊的固定 bytes、版本、生效日及到期／無到期聲明。

## 技術能力文件

- 可執行操作及輸入輸出 schema。
- 官方 endpoint／output／redirect hosts。
- 商品與規格精確綁定欄位。
- 認證類型（只記類型，不提交 credential）。
- rate limit、quota、錯誤碼、TTL、撤銷及 readback。

## 帳號與 runtime

- 脫敏帳號資格、方案、地區、有效期限。
- runtime 必須有另行授權、允許環境、撤銷方式與核准者；技術文件本身不能代替 runtime authority。

## 資料權利

以下五項分開核對，不得互相推定：

1. 分潤 URL 建立／轉換。
2. 商品與價格資料存取。
3. 價格觀測與歷史保存。
4. 商品圖片展示。
5. 衍生歷史／統計重新展示。

每一項都需條款定位、用途、保存期限、公開展示限制、刪除／更正義務及撤銷效果。

## 不足時的狀態

缺任一必要證據時，對應 gate 為 `UNVERIFIED`、`DENIED`、`CANDIDATE_REVIEW_REQUIRED` 或 `SOURCE_BLOCKED`。不得補猜 endpoint、host、click URL 或權利。
