# C09 威脅模型

- 合成來源冒充 licensed：比較 actual／declared class 與 `synthetic:c09:` source ID。
- 私密資料滲入：遞迴掃描 credential 欄位及 Bearer、private-key、userinfo URL 型態。
- 權利擴張：四維度採 exact scope，未知欄位、缺欄或過寬 scope 皆拒絕。
- 證據替換：source、coupon 與 rights 的 evidence ID、locator、SHA 必須一致。
- 身分誤併：product、SKU、seller、condition、package、quantity 均為必要欄位；coupon identity 必須精確相符。
- 時間繞過：只接受 `Z` 時區；檢查 future capture、capture/observation 次序、coupon 與 rights expiry。
- JSON ambiguity：拒絕 duplicate key、非 UTF-8、超過 256 KiB、未知欄位。
- 副作用：verifier 為純離線函式，不存檔、不連線、不寫 B11、不中介 CTA。
