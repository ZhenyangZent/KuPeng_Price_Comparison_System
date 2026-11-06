# 來源資料使用授權詢問草稿

以下內容僅供使用者自行審閱與寄送。S01 未寄信、未註冊、未登入、未購買服務。

## A. Coupang Taiwan／Coupang Partners

主旨：詢問台灣商品資料 feed/API 與私人價格追蹤用途之書面授權

您好：

我正在開發一個只供本人使用的台灣商品價格觀測工具，希望透過正式、可撤銷且可稽核的方式取得 Coupang Taiwan 商品候選資料。請協助確認是否有適用於台灣市場的 product feed、Coupang Partners API、deep-link API 或其他合作資料方案，並書面說明：

1. 是否允許未預先收藏商品的程式化 discovery、私人比價、歷史保存、衍生分析及本機提醒；
2. 台灣目錄覆蓋、正式 endpoint/feed、認證、配額、更新頻率、費率與版本通知；
3. 可用欄位（canonical URL、product/vendor item、賣家、價格、庫存、數量、配送類型、WOW、券、運費、稅費、觀測與失效時間）；
4. 保存期、備份、刪除、歸因、再利用、終止與撤銷要求；
5. 此用途是否需要特定會員／商業資格，及應簽署的條款。

本工具不會領券、加入購物車、下單或付款；在取得書面授權前也不會擷取商品或呼叫未記載 API。謝謝。

## B. 飛比 BI

主旨：詢問 Coupang Taiwan 資料之特約機器輸出、保存與衍生使用權

您好：

想詢問飛比 BI 是否能以特約方式提供 Coupang Taiwan 的商品候選資料。請在報價／訂單中明確確認：

1. 貴公司有權提供及再授權相關上游資料；
2. 允許 API/feed/export、持續下載、私人價格歷史保存、去重、衍生分析與本機提醒；
3. 覆蓋欄位、更新頻率、配額、費率、SLA、錯誤更正與停用通知；
4. 資料是否包含 canonical URL、exact SKU/vendor item、賣家、價格、庫存、配送/WOW/運費與 provenance 時間；
5. 保存、備份、公開限制、歸因、刪除、終止後處理與稽核要求。

若預設 BI 約款僅供企業內部參考或不涵蓋上述權利，請提供可適用的特別條款。謝謝。

## C. Meta Threads App Review 說明草稿

用途：使用正式 Threads keyword search，只找公開貼文中的一般購物線索，顯示給已授權使用者人工檢視。

資料處理聲明：

- 只使用經 App Review 核准的 `threads_basic`／`threads_keyword_search` 與正式 endpoint。
- 保存最小必要的 post ID、文字摘要、permalink、timestamp 與 permission version。
- 不把貼文當成價格、庫存、SKU、WOW、運費或完整成本證據。
- 支援 token 撤銷、貼文刪除／更新、保存期限與使用者資料刪除要求。
- 不使用 scraping、未記載 endpoint 或繞過 app review。

在 Meta 確認 use case、permission 與資料保存要求前，不啟用此來源。
