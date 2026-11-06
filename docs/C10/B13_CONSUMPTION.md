# B13 消費 C10 的契約

CONTRACT: `CDH-B13-C10-CONSUMPTION-CONTRACT-1`

B13 必須在 exact C09 source hash 與 C10 validator 通過後，才可接受 `ALLOW_SYNTHETIC_PREFLIGHT`。同時必須確認 source class 是 `SYNTHETIC_PREFLIGHT`，以及 canonical write、B11 mutation、runtime、public display、CTA 全為 false、click URL 為 null。

缺少 C10、C09 hash 不符、exception、unknown schema、decision deny 或 invariant 弱化都必須 fail closed。B13 不得回傳完整原始 CSV/JSON，不得將 C10 output 當作正式資料寫入授權。

本輪 B13 尚無精確 release 可供 C10 實際 adapter replay，因此狀態為 `NOT_RUN_INPUT_UNAVAILABLE`；這份文件是供並行 B 工作線採用的版本化契約，不修改 B 原始碼。
