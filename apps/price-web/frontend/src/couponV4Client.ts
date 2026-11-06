import { assertSameB10Snapshot, B10WireError, parseB10Detail, parseB10Search } from "./b10RuntimeSchema";
import type { B10DetailResponse, B10Product, B10SearchResponse } from "./b10WireTypes";

export class CouponV4HttpError extends Error {
  constructor(public readonly status: number, public readonly code: string, detail: string) { super(detail); this.name = "CouponV4HttpError"; }
}

interface Cached { etag: string; body: unknown }
export class CouponV4Client {
  private readonly cache = new Map<string, Cached>();
  constructor(private readonly basePath = "/cdh-coupon-v4", private readonly timeoutMs = 5000) {}

  private async json(path: string, signal?: AbortSignal): Promise<unknown> {
    const url = `${this.basePath}${path}`, cached = this.cache.get(url), controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(new DOMException("V4 request timed out", "TimeoutError")), this.timeoutMs);
    const abort = () => controller.abort(signal?.reason);
    if (signal) { if (signal.aborted) abort(); else signal.addEventListener("abort", abort, { once: true }); }
    try {
      const response = await fetch(url, { method: "GET", cache: "no-store", credentials: "omit", redirect: "error", headers: { Accept: "application/json", ...(cached ? { "If-None-Match": cached.etag } : {}) }, signal: controller.signal });
      if (response.status === 304) {
        if (!cached) throw new CouponV4HttpError(304, "EMPTY_304_CACHE", "收到 304 但沒有可驗證的本機快取");
        return cached.body;
      }
      const contentType = response.headers.get("content-type") ?? "";
      if (!contentType.toLowerCase().startsWith("application/json")) throw new CouponV4HttpError(response.status, "INVALID_CONTENT_TYPE", "V4 API 未回傳 JSON");
      const body = await response.json();
      if (!response.ok) {
        const record = body && typeof body === "object" ? body as Record<string, unknown> : {};
        const error = record.error && typeof record.error === "object" ? record.error as Record<string, unknown> : {};
        throw new CouponV4HttpError(response.status, typeof error.code === "string" ? error.code : "HTTP_ERROR", typeof error.detail === "string" ? error.detail : `HTTP ${response.status}`);
      }
      const etag = response.headers.get("etag");
      if (etag) this.cache.set(url, { etag, body });
      return body;
    } finally {
      window.clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
    }
  }

  async search(query = "", signal?: AbortSignal): Promise<B10SearchResponse> {
    return parseB10Search(await this.json(`/api/v4/products?q=${encodeURIComponent(query)}&page=1&limit=100`, signal));
  }

  async detail(seriesKey: string, expected: B10Product, search: B10SearchResponse, signal?: AbortSignal): Promise<B10DetailResponse> {
    const detail = parseB10Detail(await this.json(`/api/v4/products/${encodeURIComponent(seriesKey)}`, signal), seriesKey, expected);
    assertSameB10Snapshot(search, detail);
    return detail;
  }
}

export const describeV4Error = (error: unknown) => {
  if (error instanceof CouponV4HttpError) return `${error.code}（HTTP ${error.status}）：${error.message}`;
  if (error instanceof B10WireError) return `${error.code}：${error.message}`;
  if (error instanceof DOMException && error.name === "AbortError") return "請求已取消";
  if (error instanceof DOMException && error.name === "TimeoutError") return "本機 V4 API 逾時";
  return error instanceof Error ? error.message : "V4 API 發生未知錯誤";
};
