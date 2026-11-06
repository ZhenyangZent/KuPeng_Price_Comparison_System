# A04 → D04 唯讀歷史報表介面提案

狀態：`PROPOSAL_ONLY`。A04 不修改 D04，也不要求 D04 在本輪實作此檔案。

建議固定唯讀路徑：`data/exchange/reports/d04/latest.json`。

最小欄位：

```json
{
  "contract": "CDH-D04-PRICE-HISTORY-1",
  "source_status": "SOURCE_BLOCKED",
  "generated_at": "2026-11-04T00:00:00Z",
  "items": []
}
```

A04 只讀且 fail-closed：檔案不存在時顯示「歷史報表尚未啟用」；格式、版本、來源狀態或時間不符時顯示無效，不會改寫、刪除或產生替代報表。正式欄位擴充需由 Orchestrator 與 D04 工作線另行核准。
