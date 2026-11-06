import type { ManualCommit, ManualObservationDraft, ManualObservationRequest, ManualPreview, ManualSession, PrivateDetail, PrivateSearch } from "./manualObservationTypes";

export class ManualObservationError extends Error {
  constructor(public readonly code: string, message: string, public readonly status = 0) { super(message); this.name = "ManualObservationError"; }
}
const object = (value: unknown, label: string): Record<string, unknown> => { if (!value || typeof value !== "object" || Array.isArray(value)) throw new ManualObservationError("B15_WIRE_INVALID", `${label} 不是物件`); return value as Record<string, unknown>; };
const exact = (value: Record<string, unknown>, keys: string[], label: string) => { const actual = Object.keys(value).sort(), expected = [...keys].sort(); if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new ManualObservationError("B15_WIRE_INVALID", `${label} 欄位不符合契約`); };
const string = (value: unknown, label: string, pattern = /^.{1,1024}$/u) => { if (typeof value !== "string" || !pattern.test(value)) throw new ManualObservationError("B15_WIRE_INVALID", `${label} 無效`); return value; };
const integer = (value: unknown, label: string, minimum = 0) => { if (!Number.isSafeInteger(value) || (value as number) < minimum) throw new ManualObservationError("B15_WIRE_INVALID", `${label} 無效`); return value as number; };
const bool = (value: unknown, label: string) => { if (typeof value !== "boolean") throw new ManualObservationError("B15_WIRE_INVALID", `${label} 無效`); return value; };
const enumValue = <T extends string>(value: unknown, allowed: readonly T[], label: string) => { if (typeof value !== "string" || !allowed.includes(value as T)) throw new ManualObservationError("B15_WIRE_INVALID", `${label} 無效`); return value as T; };
const hash = (value: unknown, label: string) => string(value, label, /^[a-f0-9]{64}$/);

export function buildManualRequest(draft: ManualObservationDraft, submissionId: string): ManualObservationRequest {
  const hasCoupon = draft.user_reported_coupon_price_twd !== null;
  const evidence = hasCoupon ? draft.coupon_evidence_level : "NONE";
  return {
    schema_version: "CDH-B15-MANUAL-OBSERVATION-1", submission_id: submissionId, title: draft.title,
    identity: { platform: "COUPANG_TW", product_id: draft.product_id, sku_id: draft.sku_id, seller_id: draft.seller_id, condition: "NEW", package_signature: draft.package_signature, currency: "TWD" },
    observed_at: draft.observed_at, quantity: draft.quantity, before_coupon_price_twd: draft.before_coupon_price_twd,
    user_reported_coupon: { status: hasCoupon ? "USER_REPORTED" : "NONE", price_twd: draft.user_reported_coupon_price_twd, eligibility: hasCoupon ? draft.coupon_eligibility : "UNKNOWN", evidence_level: evidence, evidence_note: hasCoupon && evidence !== "NONE" ? draft.coupon_evidence_note : null, valid_from: null, valid_until: null },
    shipping: { status: "UNKNOWN", shipping_fee_twd: null, mandatory_fee_twd: null },
    source: { source_class: "USER_ENTERED", visibility: "PRIVATE_LOCAL", note: draft.source_note },
  };
}

export function parseManualSession(value: unknown): ManualSession {
  const item = object(value, "session"); exact(item, ["schema_version", "csrf_token", "storage_scope", "baselines"], "session");
  const baselines = object(item.baselines, "baselines"), keys = Object.keys(baselines).sort(), b15Keys = ["B11", "B14", "C11_REV2"].sort(), b16Keys = ["A14", "B13", "B14", "B15_REV2", "C11_REV2"].sort();
  const matches = (expected: string[]) => keys.length === expected.length && keys.every((key, index) => key === expected[index]);
  if (!matches(b15Keys) && !matches(b16Keys)) throw new ManualObservationError("B15_WIRE_INVALID", "baselines 欄位不符合 B15 或 B16 精確契約");
  const validated = Object.fromEntries(keys.map((key) => [key, hash(baselines[key], key)]));
  return { schema_version: enumValue(item.schema_version, ["CDH-B15-PRIVATE-OBSERVATION-API-1"] as const, "schema_version"), csrf_token: string(item.csrf_token, "csrf_token"), storage_scope: enumValue(item.storage_scope, ["PRIVATE_LOCAL_ONLY"] as const, "storage_scope"), baselines: validated as ManualSession["baselines"] };
}

export function parseManualPreview(value: unknown): ManualPreview {
  const item = object(value, "preview"); exact(item, ["schema_version", "mode", "preview_id", "confirm_token", "expires_in_seconds", "will_save", "warnings", "database_write_count"], "preview");
  if (item.database_write_count !== 0) throw new ManualObservationError("B15_SAFETY_INVALID", "預覽不得寫入資料庫");
  if (!Array.isArray(item.warnings) || item.warnings.some((entry) => typeof entry !== "string")) throw new ManualObservationError("B15_WIRE_INVALID", "warnings 無效");
  const saved = object(item.will_save, "will_save"), identity = object(saved.identity, "identity"), coupon = object(saved.user_reported_coupon, "user_reported_coupon"), source = object(saved.source, "source");
  if (saved.confirmed_after_coupon_price_twd !== null) throw new ManualObservationError("B15_SAFETY_INVALID", "使用者自報券價不得升格為確認券價");
  if (source.source_class !== "USER_ENTERED" || source.visibility !== "PRIVATE_LOCAL" || source.platform_verified !== false) throw new ManualObservationError("B15_SAFETY_INVALID", "來源分類不是私人手動輸入");
  hash(saved.series_key, "series_key"); string(saved.observed_at, "observed_at"); integer(saved.before_coupon_price_twd, "before_coupon_price_twd");
  return { schema_version: enumValue(item.schema_version, ["CDH-B15-PRIVATE-OBSERVATION-API-1"] as const, "schema_version"), mode: enumValue(item.mode, ["PREVIEW_NO_DATABASE_WRITE"] as const, "mode"), preview_id: string(item.preview_id, "preview_id"), confirm_token: string(item.confirm_token, "confirm_token"), expires_in_seconds: integer(item.expires_in_seconds, "expires_in_seconds", 1), will_save: { ...saved, identity, user_reported_coupon: coupon, source } as ManualPreview["will_save"], warnings: item.warnings as string[], database_write_count: 0 };
}

export function parseManualCommit(value: unknown): ManualCommit {
  const item = object(value, "confirm"); exact(item, ["schema_version", "status", "observation_id", "series_key", "idempotent_replay", "backup_created", "backup_cleanup_removed_count", "data_version"], "confirm");
  return { schema_version: enumValue(item.schema_version, ["CDH-B15-PRIVATE-OBSERVATION-API-1"] as const, "schema_version"), status: enumValue(item.status, ["SAVED_PRIVATE_LOCAL"] as const, "status"), observation_id: string(item.observation_id, "observation_id"), series_key: hash(item.series_key, "series_key"), idempotent_replay: bool(item.idempotent_replay, "idempotent_replay"), backup_created: bool(item.backup_created, "backup_created"), backup_cleanup_removed_count: integer(item.backup_cleanup_removed_count, "backup_cleanup_removed_count"), data_version: string(item.data_version, "data_version") };
}

function parseProduct(value: unknown) {
  const item = object(value, "product");
  if (item.data_classification !== "PRIVATE_LOCAL_USER_ENTERED" || item.cta_enabled !== false || item.click_url !== null || item.confirmed_coupon_price_twd !== null) throw new ManualObservationError("B15_SAFETY_INVALID", "私有資料被升格或啟用外連");
  const permission = object(item.source_permission, "source_permission");
  if (permission.allowed !== true || permission.state !== "PRIVATE_LOCAL_ONLY" || permission.reason !== "USER_EXPLICITLY_CONFIRMED_LOCAL_STORAGE") throw new ManualObservationError("B15_SAFETY_INVALID", "私有來源權限無效");
  hash(item.series_key, "series_key"); integer(item.before_coupon_price_twd, "before_coupon_price_twd"); return item;
}
function parseTrack(value: unknown, label: string) { if (!Array.isArray(value)) throw new ManualObservationError("B15_WIRE_INVALID", `${label} 無效`); return value.map((entry) => { const point = object(entry, label); integer(point.price_twd, `${label}.price_twd`); string(point.observed_at, `${label}.observed_at`); return point; }); }
function parseQuality(value: unknown, label: string) { const item = object(value, label); exact(item, ["raw_sample_count", "truncated", "daily_representatives"], label); if (!Array.isArray(item.daily_representatives)) throw new ManualObservationError("B15_WIRE_INVALID", `${label}.daily 無效`); item.daily_representatives.forEach((entry) => { const point = object(entry, "daily"); integer(point.representative_price_twd, "representative_price_twd"); integer(point.sample_count, "sample_count", 1); string(point.taipei_date, "taipei_date", /^\d{4}-\d{2}-\d{2}$/); }); return item; }

export function parsePrivateSearch(value: unknown): PrivateSearch {
  const item = object(value, "search"); exact(item, ["schema_version", "data_classification", "data_version", "page", "limit", "total", "items"], "search");
  if (item.schema_version !== "CDH-PRIVATE-PRICE-V1" || item.data_classification !== "PRIVATE_LOCAL_USER_ENTERED" || !Array.isArray(item.items)) throw new ManualObservationError("B15_WIRE_INVALID", "私有 Search 契約無效");
  item.items.forEach(parseProduct); return item as unknown as PrivateSearch;
}
export function parsePrivateDetail(value: unknown): PrivateDetail {
  const item = object(value, "detail"); exact(item, ["schema_version", "data_classification", "data_version", "product", "history", "history_quality"], "detail");
  if (item.schema_version !== "CDH-PRIVATE-PRICE-V1" || item.data_classification !== "PRIVATE_LOCAL_USER_ENTERED") throw new ManualObservationError("B15_WIRE_INVALID", "私有 Detail 契約無效");
  parseProduct(item.product); const history = object(item.history, "history"), quality = object(item.history_quality, "history_quality"); exact(history, ["before_coupon", "confirmed_after_coupon", "user_reported_after_coupon"], "history"); exact(quality, ["before_coupon", "confirmed_after_coupon", "user_reported_after_coupon"], "history_quality");
  for (const key of ["before_coupon", "confirmed_after_coupon", "user_reported_after_coupon"] as const) { parseTrack(history[key], key); parseQuality(quality[key], key); }
  if ((history.confirmed_after_coupon as unknown[]).length !== 0) throw new ManualObservationError("B15_SAFETY_INVALID", "私人自報券價不得進入已確認券後歷史");
  return item as unknown as PrivateDetail;
}

export class ManualObservationClient {
  private sessionValue: ManualSession | null = null;
  constructor(private readonly basePath = "/cdh-private-observations", private readonly timeoutMs = 8000) {}
  private async request(path: string, options: RequestInit = {}, signal?: AbortSignal) {
    const controller = new AbortController(), timeout = window.setTimeout(() => controller.abort(new DOMException("B15 request timed out", "TimeoutError")), this.timeoutMs), abort = () => controller.abort(signal?.reason);
    if (signal) { if (signal.aborted) abort(); else signal.addEventListener("abort", abort, { once: true }); }
    try {
      const response = await fetch(`${this.basePath}${path}`, { ...options, cache: "no-store", credentials: "omit", redirect: "error", headers: { Accept: "application/json", ...(options.headers ?? {}) }, signal: controller.signal });
      if (!(response.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) throw new ManualObservationError("B15_CONTENT_TYPE_INVALID", "B15 未回傳 JSON", response.status);
      const payload = await response.json();
      if (!response.ok) { const envelope = object(payload, "error envelope"), error = object(envelope.error, "error"); throw new ManualObservationError(typeof error.code === "string" ? error.code : "B15_HTTP_ERROR", `B15 拒絕請求：${String(error.code ?? response.status)}`, response.status); }
      return payload;
    } catch (error) { if (error instanceof ManualObservationError || error instanceof DOMException) throw error; throw new ManualObservationError("B15_INPUT_UNAVAILABLE", "B15 本機服務不可用；資料沒有保存"); }
    finally { window.clearTimeout(timeout); signal?.removeEventListener("abort", abort); }
  }
  async session(signal?: AbortSignal) { if (!this.sessionValue) this.sessionValue = parseManualSession(await this.request("/api/private-observations/v1/session", {}, signal)); return this.sessionValue; }
  async preview(draft: ManualObservationDraft, submissionId: string, signal?: AbortSignal) { const session = await this.session(signal); return parseManualPreview(await this.request("/api/private-observations/v1/preview", { method: "POST", headers: { "Content-Type": "application/json", "X-CDH-CSRF-Token": session.csrf_token }, body: JSON.stringify(buildManualRequest(draft, submissionId)) }, signal)); }
  async confirm(previewId: string, confirmToken: string, signal?: AbortSignal) { const session = await this.session(signal); return parseManualCommit(await this.request("/api/private-observations/v1/confirm", { method: "POST", headers: { "Content-Type": "application/json", "X-CDH-CSRF-Token": session.csrf_token }, body: JSON.stringify({ preview_id: previewId, confirm_token: confirmToken, explicit_confirm: true }) }, signal)); }
  async search(query: string, signal?: AbortSignal) { return parsePrivateSearch(await this.request(`/api/private-observations/v1/products?q=${encodeURIComponent(query)}&page=1&limit=20`, {}, signal)); }
  async detail(seriesKey: string, signal?: AbortSignal) { return parsePrivateDetail(await this.request(`/api/private-observations/v1/products/${encodeURIComponent(seriesKey)}`, {}, signal)); }
}
export const describeManualError = (error: unknown) => error instanceof ManualObservationError ? `${error.code}${error.status ? `（HTTP ${error.status}）` : ""}：${error.message}` : error instanceof DOMException && error.name === "TimeoutError" ? "B15 本機服務逾時；資料沒有保存" : error instanceof Error ? error.message : "手動記錄發生未知錯誤";
