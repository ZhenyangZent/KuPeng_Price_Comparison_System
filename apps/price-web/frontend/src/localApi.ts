import { parseAffiliateV2, parseDetailV2, parseErrorPayload, parseSearchV2 } from "./runtimeSchema";
import type { PriceDataClient, ProductDetailResponse, SearchResponse } from "./types";

const API_ROOT = "/cdh-local-api/api/v2";

export class LocalApiError extends Error {
  constructor(public readonly code: "UNAVAILABLE" | "HTTP_ERROR" | "INVALID_QUERY", detail: string) {
    super(detail);
    this.name = "LocalApiError";
  }
}

const inFlight = new Map<string, Promise<unknown>>();
async function rawRequest(path: string, signal?: AbortSignal): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${API_ROOT}${path}`, { method: "GET", headers: { Accept: "application/json" }, credentials: "omit", redirect: "error", cache: "no-store", signal });
  } catch {
    throw new LocalApiError("UNAVAILABLE", "本機唯讀價格 API 無法連線；未自動切換或偽造資料");
  }
  let body: unknown;
  try { body = await response.json(); } catch { throw new LocalApiError("HTTP_ERROR", "本機 API 回傳非 JSON 內容"); }
  if (!response.ok) throw new LocalApiError("HTTP_ERROR", parseErrorPayload(body) ?? `本機 API HTTP ${response.status}`);
  return body;
}
function request(path: string, signal?: AbortSignal): Promise<unknown> {
  if (signal) return rawRequest(path, signal);
  const existing = inFlight.get(path);
  if (existing) return existing;
  const pending = rawRequest(path).finally(() => inFlight.delete(path));
  inFlight.set(path, pending);
  return pending;
}

export const localApiClient: PriceDataClient = {
  mode: "LOCAL_API",
  async searchProducts(query, page = 1, limit = 20, signal?: AbortSignal): Promise<SearchResponse> {
    if (!Number.isInteger(page) || page < 1 || !Number.isInteger(limit) || limit < 1 || limit > 100) throw new LocalApiError("INVALID_QUERY", "page/limit 超出允許範圍");
    const parsed = parseSearchV2(await request(`/products?${new URLSearchParams({ q: query.trim(), page: String(page), limit: String(limit) })}`, signal));
    if (parsed.data_source_status !== "USER_RECORDED_ONLY" || parsed.data_classification !== "USER_RECORDED") throw new LocalApiError("HTTP_ERROR", "本機正式模式不可混入合成 fixture");
    return parsed;
  },
  async getProductDetail(productId, signal?: AbortSignal): Promise<ProductDetailResponse> {
    if (!productId || productId.includes("/")) throw new LocalApiError("INVALID_QUERY", "商品 ID 無效");
    const encoded = encodeURIComponent(productId);
    const [detail, affiliate] = await Promise.all([request(`/products/${encoded}`, signal), request(`/products/${encoded}/affiliate`, signal)]);
    const parsed = parseDetailV2(detail, productId);
    if (parsed.data_source_status !== "USER_RECORDED_ONLY" || parsed.data_classification !== "USER_RECORDED" || parsed.history.some((point) => point.source_type === "SYNTHETIC")) throw new LocalApiError("HTTP_ERROR", "本機正式模式不可混入合成 fixture");
    const affiliateInfo = parseAffiliateV2(affiliate, productId);
    if (JSON.stringify(parsed.affiliate) !== JSON.stringify(affiliateInfo)) throw new LocalApiError("HTTP_ERROR", "明細與分潤端點狀態不一致");
    return parsed;
  }
};
