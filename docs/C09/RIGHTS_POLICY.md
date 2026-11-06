# C09 權利維度政策

四個維度必須獨立提供證據，不得互相推定：

- `collection`：只接受 `ALLOW / SYNTHETIC_GENERATION_ONLY`。
- `retention`：只接受 `ALLOW / EPHEMERAL_STAGING_ONLY`，且未過期。
- `display`：只接受 `ALLOW / LOCAL_PREVIEW_ONLY`，且未過期。
- `link_disclosure`：本輪只接受 `DENY / NO_LINK`；staged record 的 `link_url` 必須為 `null`。

每個維度都必須綁定相同的 evidence ID、`fixture://c09/` proof locator 與 lowercase SHA-256。使用者自行輸入或上傳檔案不會自動取得蒐集、保存、展示、分享、轉售或連結揭露權。

任何 revoked、expired、scope 過寬、證據不一致或缺少維度，都整筆 `DENY`，且所有 permission 均 `BLOCKED`。
