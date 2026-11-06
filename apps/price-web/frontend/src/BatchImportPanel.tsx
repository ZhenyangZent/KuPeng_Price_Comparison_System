import { ChangeEvent, useMemo, useState } from "react";
import {
  BatchImportClient,
  describeBatchError,
  type BatchCommit,
  type BatchPreviewReady,
  type BatchPreviewRejected,
} from "./batchImportClient";
import { ImportPreviewError, previewCell, previewImportText, type ImportPreview } from "./batchImportPreview";

interface SelectedFile {
  name: string;
  bytes: Uint8Array;
}

export function BatchImportPanel() {
  const client = useMemo(() => new BatchImportClient(), []);
  const [selected, setSelected] = useState<SelectedFile | null>(null);
  const [localPreview, setLocalPreview] = useState<ImportPreview | null>(null);
  const [serverPreview, setServerPreview] = useState<BatchPreviewReady | BatchPreviewRejected | null>(null);
  const [commit, setCommit] = useState<BatchCommit | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const resetServerState = () => {
    setServerPreview(null);
    setCommit(null);
    setConfirmed(false);
  };

  const select = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    setSelected(null);
    setLocalPreview(null);
    setError("");
    resetServerState();
    if (!file) return;
    setBusy(true);
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const source = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      setLocalPreview(previewImportText(file.name, bytes.length, source));
      setSelected({ name: file.name, bytes });
    } catch (caught) {
      setError(caught instanceof ImportPreviewError
        ? `${caught.code}：${caught.message}`
        : caught instanceof TypeError
          ? "FILE_ENCODING_INVALID：檔案必須是有效 UTF-8"
          : "FILE_READ_FAILED：檔案無法讀取");
    } finally {
      setBusy(false);
    }
  };

  const requestPreview = async () => {
    if (!selected) return;
    setBusy(true);
    setError("");
    resetServerState();
    try {
      setServerPreview(await client.preview(selected.name, selected.bytes));
    } catch (caught) {
      setError(describeBatchError(caught));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!serverPreview || serverPreview.status !== "PREVIEW_READY_NO_DATABASE_WRITE" || !confirmed) return;
    setBusy(true);
    setError("");
    setCommit(null);
    try {
      setCommit(await client.confirm(serverPreview.preview_id, serverPreview.confirm_token));
    } catch (caught) {
      setError(describeBatchError(caught));
    } finally {
      setBusy(false);
    }
  };

  const ready = serverPreview?.status === "PREVIEW_READY_NO_DATABASE_WRITE" ? serverPreview : null;
  const rejected = serverPreview?.status === "PREVIEW_REJECTED" ? serverPreview : null;

  return <section className="batch-import-panel" aria-label="CSV JSON 批次匯入預覽">
    <div className="section-heading">
      <div><p className="eyebrow">A15 + B16 PRIVATE LOCAL BATCH IMPORT</p><h2>CSV／JSON 批次匯入</h2></div>
      <span>1 MiB · 最多 500 筆</span>
    </div>
    <p>檔案只以 base64 內容送往本機同源 B16；不傳本機路徑。先預覽、再明確確認才會寫入隔離私人資料庫。</p>
    <label className="batch-file-picker" htmlFor="batch-import-file">
      <span>選擇合成 CSV 或 JSON</span>
      <input id="batch-import-file" type="file" accept=".csv,.json,text/csv,application/json" onChange={(event) => void select(event)} disabled={busy}/>
    </label>
    {busy && <p role="status">處理中…</p>}
    {error && <div className="api-error" role="alert"><strong>批次匯入遭拒絕</strong><span>{error}</span></div>}

    {localPreview && <section className="batch-preview" aria-label="批次匯入本機預覽表格">
      <div className="batch-preview-summary"><strong>{localPreview.filename}</strong><span>{localPreview.format} · {localPreview.records.length} 筆 · {localPreview.byte_size} bytes</span></div>
      <div className="batch-table-scroll"><table><thead><tr>{localPreview.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{localPreview.records.map((record, row) => <tr key={row}>{localPreview.columns.map((column) => <td key={column}>{previewCell(record[column])}</td>)}</tr>)}</tbody></table></div>
      <ul className="batch-warning-list">{localPreview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
      <button className="confirm-save" type="button" onClick={() => void requestPreview()} disabled={busy}>送往 B16 安全預覽</button>
    </section>}

    {serverPreview && <section className="batch-server-preview" data-can-confirm={serverPreview.can_confirm} aria-label="B16 伺服器批次預覽">
      <div className="batch-preview-summary">
        <strong>{serverPreview.status}</strong>
        <span>{serverPreview.row_count} 筆 · database_write_count = {serverPreview.database_write_count}</span>
      </div>
      <p className="batch-server-proof">B16 已重新驗證內容；預覽階段資料庫寫入數必須維持 0。</p>
      {serverPreview.rows.length > 0 && <div className="batch-table-scroll"><table><thead><tr><th>列</th><th>動作</th><th>商品</th><th>日期</th><th>券前價</th><th>自報券價</th><th>平台確認券價</th></tr></thead><tbody>{serverPreview.rows.map((row) => <tr key={`${row.row_number}-${row.submission_id}`}><td>{row.row_number}</td><td>{row.action}</td><td>{row.title}</td><td>{row.taipei_date}</td><td>{row.before_coupon_price_twd}</td><td>{row.user_reported_coupon_price_twd ?? "—"}</td><td>{row.confirmed_after_coupon_price_twd ?? "—（未升格）"}</td></tr>)}</tbody></table></div>}
      {rejected && <div className="api-error" role="alert"><strong>逐筆驗證失敗，禁止確認</strong>{rejected.row_errors.map((item) => <span key={`${item.row_number}-${item.error}`}>第 {item.row_number} 列：{item.error}</span>)}</div>}
      {ready && <>
        <p>新紀錄 {ready.database_summary.new_count} 筆；既有冪等紀錄 {ready.database_summary.existing_idempotent_count} 筆；輸入內重複 {ready.duplicate_input_count} 筆。</p>
        <label className="explicit-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={busy}/><span>我已檢查 B16 預覽與資料身分，現在明確確認保存至隔離私人資料庫。</span></label>
        <button className="confirm-save batch-confirm" type="button" onClick={() => void confirm()} disabled={busy || !confirmed}>明確確認並保存</button>
      </>}
    </section>}

    {commit && <section className="sync-result" aria-label="B16 批次保存結果">
      <strong>{commit.http_status === 201 ? "新批次已保存" : "冪等重播，沒有新增資料"}</strong>
      <span>HTTP {commit.http_status} · 新增 {commit.inserted_count} · 既有 {commit.existing_idempotent_count} · 私人本機資料版本 {commit.data_version}</span>
      <span>自報券價仍為 USER_REPORTED；不會升格為平台確認價。</span>
    </section>}
  </section>;
}
