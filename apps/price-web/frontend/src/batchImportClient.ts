import { parseManualSession } from "./manualObservationClient";
import type { ManualSession } from "./manualObservationTypes";

export interface BatchRowSummary { row_number: number; action: string; submission_id: string; title: string; series_key: string; observed_at: string; taipei_date: string; before_coupon_price_twd: number; user_reported_coupon_price_twd: number | null; confirmed_after_coupon_price_twd: null; coupon_status: string; coupon_evidence_level: string; source_class: "USER_ENTERED"; visibility: "PRIVATE_LOCAL"; platform_verified: false }
export interface BatchRowError { row_number: number; error: string; input_sha256?: string }
export interface BatchPreviewReady { schema_version: "CDH-B16-PRIVATE-BATCH-API-1"; status: "PREVIEW_READY_NO_DATABASE_WRITE"; can_confirm: true; database_write_count: 0; preview_id: string; confirm_token: string; expires_in_seconds: number; filename: string; media_type: "text/csv" | "application/json"; file_sha256: string; row_count: number; unique_record_count: number; duplicate_input_count: number; database_summary: { new_count: number; existing_idempotent_count: number }; rows: BatchRowSummary[]; warnings: string[] }
export interface BatchPreviewRejected { schema_version: "CDH-B16-PRIVATE-BATCH-API-1"; status: "PREVIEW_REJECTED"; can_confirm: false; database_write_count: 0; filename: string; media_type: "text/csv" | "application/json"; file_sha256: string; row_count: number; valid_row_count: number; error_count: number; rows: BatchRowSummary[]; row_errors: BatchRowError[] }
export interface BatchCommit { schema_version: "CDH-B16-PRIVATE-BATCH-API-1"; status: "BATCH_SAVED_PRIVATE_LOCAL"; batch_id: string; inserted_count: number; existing_idempotent_count: number; duplicate_input_count: number; idempotent_replay: boolean; backup_created: boolean; backup_cleanup_removed_count: number; observation_ids: string[]; data_version: string; http_status: 200 | 201 }

export class BatchImportError extends Error { constructor(public readonly code: string, message: string, public readonly status = 0) { super(message); this.name = "BatchImportError"; } }
const record = (value: unknown, label: string): Record<string, unknown> => { if (!value || typeof value !== "object" || Array.isArray(value)) throw new BatchImportError("B16_WIRE_INVALID", `${label} 不是物件`); return value as Record<string, unknown>; };
const exact = (item: Record<string, unknown>, keys: string[], label: string) => { const actual = Object.keys(item).sort(), expected = [...keys].sort(); if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new BatchImportError("B16_WIRE_INVALID", `${label} 欄位不符合契約`); };
const text = (value: unknown, label: string) => { if (typeof value !== "string" || !value.length) throw new BatchImportError("B16_WIRE_INVALID", `${label} 無效`); return value; };
const integer = (value: unknown, label: string) => { if (!Number.isSafeInteger(value) || (value as number) < 0) throw new BatchImportError("B16_WIRE_INVALID", `${label} 無效`); return value as number; };
const boolean = (value: unknown, label: string) => { if (typeof value !== "boolean") throw new BatchImportError("B16_WIRE_INVALID", `${label} 無效`); return value; };
const hash = (value: unknown, label: string) => { const result = text(value, label); if (!/^[a-f0-9]{64}$/.test(result)) throw new BatchImportError("B16_WIRE_INVALID", `${label} 無效`); return result; };

function parseRow(value: unknown): BatchRowSummary {
  const item = record(value, "row"); exact(item, ["row_number", "action", "submission_id", "title", "series_key", "observed_at", "taipei_date", "before_coupon_price_twd", "user_reported_coupon_price_twd", "confirmed_after_coupon_price_twd", "coupon_status", "coupon_evidence_level", "source_class", "visibility", "platform_verified"], "row");
  if (item.confirmed_after_coupon_price_twd !== null || item.platform_verified !== false || item.source_class !== "USER_ENTERED" || item.visibility !== "PRIVATE_LOCAL") throw new BatchImportError("B16_SAFETY_INVALID", "批次列將私人券價升格或來源分類錯誤");
  integer(item.row_number, "row_number"); integer(item.before_coupon_price_twd, "before_coupon_price_twd"); if (item.user_reported_coupon_price_twd !== null) integer(item.user_reported_coupon_price_twd, "user_reported_coupon_price_twd"); hash(item.series_key, "series_key");
  for (const key of ["action", "submission_id", "title", "observed_at", "taipei_date", "coupon_status", "coupon_evidence_level"] as const) text(item[key], key);
  return item as unknown as BatchRowSummary;
}

export function parseBatchPreview(value: unknown, status: number): BatchPreviewReady | BatchPreviewRejected {
  const item = record(value, "preview");
  if (status === 422) {
    exact(item, ["schema_version", "status", "can_confirm", "database_write_count", "filename", "media_type", "file_sha256", "row_count", "valid_row_count", "error_count", "rows", "row_errors"], "preview rejected");
    if (item.schema_version !== "CDH-B16-PRIVATE-BATCH-API-1" || item.status !== "PREVIEW_REJECTED" || item.can_confirm !== false || item.database_write_count !== 0 || !Array.isArray(item.rows) || !Array.isArray(item.row_errors)) throw new BatchImportError("B16_WIRE_INVALID", "B16 422 預覽契約無效");
    const errors = item.row_errors.map((entry) => { const error = record(entry, "row_error"); if (!Number.isSafeInteger(error.row_number) || typeof error.error !== "string") throw new BatchImportError("B16_WIRE_INVALID", "row_error 無效"); return error as unknown as BatchRowError; });
    return { ...item, rows: item.rows.map(parseRow), row_errors: errors } as unknown as BatchPreviewRejected;
  }
  exact(item, ["schema_version", "status", "can_confirm", "database_write_count", "preview_id", "confirm_token", "expires_in_seconds", "filename", "media_type", "file_sha256", "row_count", "unique_record_count", "duplicate_input_count", "database_summary", "rows", "warnings"], "preview ready");
  if (status !== 200 || item.schema_version !== "CDH-B16-PRIVATE-BATCH-API-1" || item.status !== "PREVIEW_READY_NO_DATABASE_WRITE" || item.can_confirm !== true || item.database_write_count !== 0 || !Array.isArray(item.rows) || !Array.isArray(item.warnings)) throw new BatchImportError("B16_WIRE_INVALID", "B16 200 預覽契約無效");
  text(item.preview_id, "preview_id"); text(item.confirm_token, "confirm_token"); hash(item.file_sha256, "file_sha256"); integer(item.row_count, "row_count"); integer(item.unique_record_count, "unique_record_count"); integer(item.duplicate_input_count, "duplicate_input_count");
  const database = record(item.database_summary, "database_summary"); exact(database, ["new_count", "existing_idempotent_count"], "database_summary"); integer(database.new_count, "new_count"); integer(database.existing_idempotent_count, "existing_idempotent_count");
  return { ...item, rows: item.rows.map(parseRow), database_summary: database } as unknown as BatchPreviewReady;
}

export function parseBatchCommit(value: unknown, status: number): BatchCommit {
  const item = record(value, "confirm"), required = ["schema_version", "status", "batch_id", "inserted_count", "existing_idempotent_count", "duplicate_input_count", "idempotent_replay", "backup_created", "backup_cleanup_removed_count", "data_version"], allowed = new Set([...required, "observation_ids"]);
  if (Object.keys(item).some((key) => !allowed.has(key)) || required.some((key) => !(key in item))) throw new BatchImportError("B16_WIRE_INVALID", "confirm 欄位不符合契約");
  if (![200, 201].includes(status) || item.schema_version !== "CDH-B16-PRIVATE-BATCH-API-1" || item.status !== "BATCH_SAVED_PRIVATE_LOCAL") throw new BatchImportError("B16_WIRE_INVALID", "B16 confirm 契約無效");
  const inserted = integer(item.inserted_count, "inserted_count"), replay = boolean(item.idempotent_replay, "idempotent_replay");
  if ((status === 201 && (replay || inserted < 1)) || (status === 200 && (!replay || inserted !== 0))) throw new BatchImportError("B16_SAFETY_INVALID", "HTTP 狀態與冪等語義不一致");
  const ids = item.observation_ids ?? []; if (!Array.isArray(ids) || ids.some((id) => typeof id !== "string")) throw new BatchImportError("B16_WIRE_INVALID", "observation_ids 無效");
  return { ...item, observation_ids: ids, http_status: status } as BatchCommit;
}

const bytesToBase64 = (bytes: Uint8Array) => { let binary = ""; for (let offset = 0; offset < bytes.length; offset += 0x8000) binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + 0x8000, bytes.length))); return btoa(binary); };

export class BatchImportClient {
  private sessionValue: ManualSession | null = null;
  constructor(private readonly basePath = "/cdh-private-observations", private readonly timeoutMs = 12000) {}
  private async raw(path: string, options: RequestInit, signal?: AbortSignal) {
    const controller = new AbortController(), timeout = window.setTimeout(() => controller.abort(new DOMException("B16 request timed out", "TimeoutError")), this.timeoutMs), abort = () => controller.abort(signal?.reason);
    if (signal) { if (signal.aborted) abort(); else signal.addEventListener("abort", abort, { once: true }); }
    try { const response = await fetch(`${this.basePath}${path}`, { ...options, credentials: "omit", cache: "no-store", redirect: "error", headers: { Accept: "application/json", ...(options.headers ?? {}) }, signal: controller.signal }); if (!(response.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) throw new BatchImportError("B16_CONTENT_TYPE_INVALID", "B16 未回傳 JSON", response.status); return { status: response.status, payload: await response.json() }; }
    catch (error) { if (error instanceof BatchImportError || error instanceof DOMException) throw error; throw new BatchImportError("B16_INPUT_UNAVAILABLE", "B16 本機服務不可用；資料沒有保存"); }
    finally { window.clearTimeout(timeout); signal?.removeEventListener("abort", abort); }
  }
  private async session(signal?: AbortSignal) { if (!this.sessionValue) { const result = await this.raw("/api/private-observations/v1/session", {}, signal); if (result.status !== 200) this.raise(result.payload, result.status); this.sessionValue = parseManualSession(result.payload); } return this.sessionValue; }
  private raise(payload: unknown, status: number): never { const envelope = record(payload, "error envelope"), error = record(envelope.error, "error"); throw new BatchImportError(typeof error.code === "string" ? error.code : "B16_HTTP_ERROR", `B16 拒絕請求：${String(error.code ?? status)}`, status); }
  async preview(filename: string, bytes: Uint8Array, signal?: AbortSignal) { const session = await this.session(signal), media = filename.toLowerCase().endsWith(".csv") ? "text/csv" : filename.toLowerCase().endsWith(".json") ? "application/json" : null; if (!media) throw new BatchImportError("FILE_TYPE_UNSUPPORTED", "只接受 .csv 或 .json"); const result = await this.raw("/api/private-observations/v1/batch-preview", { method: "POST", headers: { "Content-Type": "application/json", "X-CDH-CSRF-Token": session.csrf_token }, body: JSON.stringify({ schema_version: "CDH-B16-BATCH-PREVIEW-REQUEST-1", filename, media_type: media, content_base64: bytesToBase64(bytes) }) }, signal); if (result.status === 200 || result.status === 422) return parseBatchPreview(result.payload, result.status); this.raise(result.payload, result.status); }
  async confirm(previewId: string, confirmToken: string, signal?: AbortSignal) { const session = await this.session(signal), result = await this.raw("/api/private-observations/v1/batch-confirm", { method: "POST", headers: { "Content-Type": "application/json", "X-CDH-CSRF-Token": session.csrf_token }, body: JSON.stringify({ schema_version: "CDH-B16-BATCH-CONFIRM-REQUEST-1", preview_id: previewId, confirm_token: confirmToken, explicit_confirm: true }) }, signal); if (result.status === 200 || result.status === 201) return parseBatchCommit(result.payload, result.status); this.raise(result.payload, result.status); }
}
export const describeBatchError = (error: unknown) => error instanceof BatchImportError ? `${error.code}${error.status ? `（HTTP ${error.status}）` : ""}：${error.message}` : error instanceof DOMException && error.name === "TimeoutError" ? "B16 本機服務逾時；資料沒有保存" : error instanceof Error ? error.message : "批次匯入發生未知錯誤";
