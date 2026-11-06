# A02 UI Status Matrix

| Condition | Sync label | Imported / pending / error |
|---|---|---|
| Receipt missing | `D01 尚無回執／資料仍在同步` | `狀態未知` |
| Receipt malformed/future schema | `狀態未知：D01 回執無效` | `狀態未知` |
| Snapshot absent/hash mismatch/invalid | `正在同步／尚未一致` | `狀態未知` |
| Receipt or snapshot stale | Explicit stale/unknown state | Never presented as current all-done |
| Valid matching receipt | `同步完成` or pending/error qualifier | Exact verified counts |
| New file after receipt cutoff | Valid receipt with pending qualifier | Pending increments |
| Imported file remains in inbox | Valid matching receipt | Imported increments; pending does not |
| Quarantined file | Valid matching receipt | Error increments; imported does not |

`原始收件檔` always includes the clarification `僅檔案數，不等於待處理`.
