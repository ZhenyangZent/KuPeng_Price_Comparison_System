# A03 架構與信任邊界

## 資料流

`QFileDialog / 手動表單` → `importers / exchange validation` → `submission_*.json` → `D03 固定 CLI` → `D01 SQLite + Receipt/Snapshot`。

GUI 僅負責建立契約化 JSON、唯讀顯示 Snapshot/Receipt，以及驗證 D03 回覆。它不持有 SQLite writer，也不能從商品欄位產生命令。D03 回覆必須符合 `CDH-LOCAL-MANUAL-SYNC-1`；來源必須維持 `SOURCE_BLOCKED`，資料範圍必須是 `USER_PROVIDED_LOCAL_ONLY`。

## 模組

- `a01_app/importers.py`：有界 UTF-8 CSV/JSON 匯入、逐列驗證、確定性重播 ID。
- `a01_app/d03_client.py`：固定 CLI、`shell=False`、逾時與輸出上限、嚴格 JSON 信任邊界。
- `a01_app/manual_history.py`：合併等待同步 inbox 與 Snapshot 的唯讀呈現。
- `a01_app/gui.py`：非阻塞 worker、操作鎖、明確確認、失敗狀態與來源標示。

## 零元與未知條件

整數零可作為使用者觀測保存，但 `qualification_state` 保持 `UNVERIFIED`；`shipping_fee_twd` 在運費未知時為 null。A03 不建立「確認零元」、「確認免運」或「可購買」事件。

## 併行 D03 工作線

A03 執行期間專案中出現獨立 D03 工作線。A03 沒有寫入或執行該工作線；只以固定介面偵測其存在。受保護範圍比對將這些新增檔案獨立列為 `external_concurrent_d03_*`，不把它們計入 A03 變更，也不隱藏其存在。
