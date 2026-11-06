import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { assertSameB10Snapshot, parseB10Detail, parseB10Search } from "../src/b10RuntimeSchema";
import { CouponV4Client } from "../src/couponV4Client";

const identity = { platform: "COUPANG_TW", product_id: "SYN-P-1", sku_id: "SYN-SKU-1", seller_id: "SYN-SELLER-1", condition: "NEW", package_signature: "1x100ml" };
const coupon = { coupon_id: "SYN-COUPON-1", status: "CONFIRMED_APPLICABLE", discount_twd: 50, discount_scope: "UNIT", already_included_in_base: false, eligibility_profile: "SYN-ELIGIBLE-PROFILE", valid_from: "2026-11-01T00:00:00Z", valid_until: "2026-11-30T23:59:59Z", scope_evidence: "SYN-EVIDENCE", pre_coupon_comparison_source: null, evaluation_reasons: [] };
const product = { series_key: "series-1", title: "B10 Synthetic coupon item", series_identity: identity, data_classification: "SYNTHETIC_FIXTURE", source_id: "SYN-SOURCE-1", observed_at: "2026-11-04T02:00:00Z", base_price_twd: 99, before_coupon_price_twd: 99, coupon, confirmed_coupon_price_twd: 49, possible_coupon_price_twd: null, display_price_twd: 49, display_basis: "CONFIRMED_COUPON", minimum_purchase_quantity: 1, minimum_item_spend_twd: 49, shipping_status: "UNKNOWN", required_total_twd: null, source_permission: { allowed: true, state: "ACTIVE_SYNTHETIC_FIXTURE", reason: "SOURCE_PERMISSION_ACTIVE" }, quality_flags: [] };
const unavailableProduct = { ...product, title: "B10 Revoked source", base_price_twd: null, before_coupon_price_twd: null, confirmed_coupon_price_twd: null, display_price_twd: null, display_basis: "PRICE_UNAVAILABLE", minimum_item_spend_twd: null, coupon: { ...coupon, status: "NONE", coupon_id: null, discount_twd: null, discount_scope: "NONE", eligibility_profile: null, valid_from: null, valid_until: null, scope_evidence: null }, source_permission: { allowed: false, state: "REVOKED", reason: "SOURCE_PERMISSION_REVOKED" }, quality_flags: ["SOURCE_PERMISSION_REVOKED"] };
const envelope = { schema_version: "CDH-COUPON-PRICE-V4", data_classification: "SYNTHETIC_FIXTURE", data_version: '"snapshot-1"' };
const searchPayload = { ...envelope, items: [product], page: 1, limit: 100, total: 1 };
const detailPayload = { ...envelope, product, history: { before_coupon: [{ observed_at: "2026-11-04T02:00:00Z", price_twd: 99, source_id: "SYN-SOURCE-1", comparison_source: "SYN-SOURCE-1", series_key: "series-1" }], confirmed_after_coupon: [{ observed_at: "2026-11-04T02:00:00Z", price_twd: 49, coupon_id: "SYN-COUPON-1", eligibility_profile: "SYN-ELIGIBLE-PROFILE", source_id: "SYN-SOURCE-1", scope_evidence: "SYN-EVIDENCE", series_key: "series-1" }] }, history_quality: { before_coupon: { raw_sample_count: 1, daily_representatives: [{ taipei_date: "2026-11-04", representative_price_twd: 99, sample_count: 1 }], truncated: false }, confirmed_after_coupon: { raw_sample_count: 1, daily_representatives: [{ taipei_date: "2026-11-04", representative_price_twd: 49, sample_count: 1 }], truncated: false } } };
const jsonResponse = (body: unknown, status = 200, headers: Record<string,string> = {}) => new Response(status === 304 ? null : JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("A10 strict B10 canonical parser", () => {
  it("parses actual Search and Detail envelopes and binds exact identity", () => {
    const search = parseB10Search(searchPayload), detail = parseB10Detail(detailPayload, "series-1", search.items[0]);
    expect(search.items[0].display_price_twd).toBe(49);
    expect(detail.history.before_coupon[0].price_twd).toBe(99);
    expect(detail.history.confirmed_after_coupon[0].price_twd).toBe(49);
    expect(() => assertSameB10Snapshot(search, detail)).not.toThrow();
  });

  it("supports explicit multi-item minimum spend without inventing checkout total", () => {
    const multi = { ...product, base_price_twd: 100, before_coupon_price_twd: 100, confirmed_coupon_price_twd: 75, display_price_twd: 75, minimum_purchase_quantity: 2, minimum_item_spend_twd: 150, coupon: { ...coupon, discount_scope: "ORDER_TOTAL" } };
    const parsed = parseB10Search({ ...searchPayload, items: [multi] });
    expect(parsed.items[0]).toMatchObject({ display_price_twd: 75, minimum_purchase_quantity: 2, minimum_item_spend_twd: 150, required_total_twd: null });
  });

  it("keeps PRICE_UNAVAILABLE distinct from zero and rejects stale permission prices", () => {
    expect(parseB10Search({ ...searchPayload, items: [unavailableProduct] }).items[0].display_price_twd).toBeNull();
    expect(() => parseB10Search({ ...searchPayload, items: [{ ...unavailableProduct, display_price_twd: 0, display_basis: "BASE_PRICE", minimum_item_spend_twd: 0 }] })).toThrow(/權限失效/);
  });

  it("rejects Search/Detail identity, series, snapshot and history-count mixing", () => {
    const search = parseB10Search(searchPayload);
    expect(() => parseB10Detail({ ...detailPayload, product: { ...product, series_identity: { ...identity, sku_id: "OTHER" } } }, "series-1", search.items[0])).toThrow(/精確商品身分/);
    expect(() => parseB10Detail({ ...detailPayload, history: { ...detailPayload.history, before_coupon: [{ ...detailPayload.history.before_coupon[0], series_key: "OTHER" }] } }, "series-1", search.items[0])).toThrow(/series_key/);
    const detail = parseB10Detail({ ...detailPayload, data_version: '"snapshot-2"' }, "series-1", search.items[0]);
    expect(() => assertSameB10Snapshot(search, detail)).toThrow(/data_version/);
    expect(() => parseB10Detail({ ...detailPayload, history_quality: { ...detailPayload.history_quality, before_coupon: { ...detailPayload.history_quality.before_coupon, raw_sample_count: 2 } } }, "series-1")).toThrow(/實際歷史/);
  });
});

describe("A10 V4 HTTP client", () => {
  it("uses verified ETag cache for 304 and rejects an empty 304", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(searchPayload, 200, { etag: '"snapshot-1"' })).mockResolvedValueOnce(jsonResponse(null, 304));
    vi.stubGlobal("fetch", fetchMock);
    const client = new CouponV4Client("/test");
    expect((await client.search()).total).toBe(1);
    expect((await client.search()).total).toBe(1);
    expect(fetchMock.mock.calls[1][1]?.headers).toMatchObject({ "If-None-Match": '"snapshot-1"' });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(null, 304)));
    await expect(new CouponV4Client("/empty").search()).rejects.toThrow(/沒有可驗證/);
  });

  it.each([[404,"NOT_FOUND"],[500,"SERVER_FAILURE"]])("surfaces HTTP %i without fixture fallback", async (status, code) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ error: { code, detail: "failure" } }, status)));
    await expect(new CouponV4Client("/test").search()).rejects.toMatchObject({ status, code });
  });

  it("honors caller cancellation", async () => {
    vi.stubGlobal("fetch", vi.fn((_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true }))));
    const controller = new AbortController(), promise = new CouponV4Client("/test", 1000).search("", controller.signal);
    controller.abort();
    await expect(promise).rejects.toBeDefined();
  });

  it("times out a non-responsive B10 request", async () => {
    vi.stubGlobal("fetch", vi.fn((_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true }))));
    await expect(new CouponV4Client("/test", 10).search()).rejects.toMatchObject({ name: "TimeoutError" });
  });
});

describe("A10 actual-wire UI", () => {
  it("renders B10 Search+Detail response, dual raw history and disabled CTA", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(searchPayload, 200, { etag: '"snapshot-1"' })).mockResolvedValueOnce(jsonResponse(detailPayload, 200, { etag: '"snapshot-1"' })));
    history.replaceState({}, "", "/?mode=synthetic&contract=v4"); render(<App/>);
    expect(await screen.findByText("B10 Synthetic coupon item")).toBeInTheDocument();
    expect(await screen.findByText("NT$ 49", { selector: ".price-block strong" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "B10 券前商品價歷史" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "B10 已確認券後商品價歷史" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "B11 券前每日代表價" })).toHaveTextContent("NT$ 99");
    expect(screen.getByRole("region", { name: "B11 已確認券後每日代表價" })).toHaveTextContent("NT$ 49");
    expect(screen.getByRole("region", { name: "四組價格歷史摘要" })).toHaveTextContent("券前 raw1 筆已確認券後 raw1 筆券前 daily1 日已確認券後 daily1 日");
    expect(document.querySelector('[data-history-basis="before_coupon"][data-history-granularity="raw"] [data-price-twd="99"]')).toBeInTheDocument();
    expect(document.querySelector('[data-history-basis="confirmed_after_coupon"][data-history-granularity="raw"] [data-price-twd="49"]')).toBeInTheDocument();
    expect(document.querySelector('[data-history-basis="before_coupon"][data-history-granularity="daily"] [data-representative-price-twd="99"][data-sample-count="1"]')).toBeInTheDocument();
    expect(document.querySelector('[data-history-basis="confirmed_after_coupon"][data-history-granularity="daily"] [data-representative-price-twd="49"][data-sample-count="1"]')).toBeInTheDocument();
    expect(screen.getByRole("note", { name: /這是商品觀測價/ })).toHaveTextContent("UNKNOWN 不等於 NT$0");
    expect(document.querySelector(".app-shell")).toHaveClass("coupon-mode");
    expect(screen.getByRole("button", { name: "正式連結尚未核准" })).toBeDisabled();
  });

  it("submits the focused V4 search input with Enter", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(searchPayload, 200))
      .mockResolvedValueOnce(jsonResponse(detailPayload, 200))
      .mockResolvedValueOnce(jsonResponse(searchPayload, 200))
      .mockResolvedValueOnce(jsonResponse(detailPayload, 200));
    vi.stubGlobal("fetch", fetchMock); history.replaceState({}, "", "/?mode=synthetic&contract=v4"); render(<App/>);
    await screen.findByText("B10 Synthetic coupon item");
    const input = screen.getByRole("textbox", { name: "搜尋 B10 商品、SKU 或商品 ID" });
    fireEvent.change(input, { target: { value: "SYN-SKU-1" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(String(fetchMock.mock.calls[2][0])).toContain("q=SYN-SKU-1");
  });

  it("reports a real API failure and retries instead of showing fixtures", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ error: { code: "SERVER_FAILURE", detail: "boom" } }, 500)).mockResolvedValueOnce(jsonResponse(searchPayload, 200, { etag: '"snapshot-1"' })).mockResolvedValueOnce(jsonResponse(detailPayload, 200));
    vi.stubGlobal("fetch", fetchMock); history.replaceState({}, "", "/?mode=synthetic&contract=v4"); render(<App/>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/未載入示範資料/);
    expect(screen.queryByText("SYNTHETIC｜CONFIRMED")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重試 API" }));
    expect(await screen.findByText("B10 Synthetic coupon item")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });

  it("renders an empty filtered Search without inventing a product or fixture", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ ...searchPayload, items: [], total: 0 }, 200, { etag: '"empty"' })));
    history.replaceState({}, "", "/?mode=synthetic&contract=v4&q=missing"); render(<App/>);
    expect(await screen.findByText("V4 snapshot 有商品，但查無符合結果")).toBeInTheDocument();
    expect(screen.queryByText("B10 Synthetic coupon item")).not.toBeInTheDocument();
    expect(screen.getByText("請選擇 V4 商品序列")).toBeInTheDocument();
  });

  it("keeps a revoked source unavailable with empty histories and CTA disabled", async () => {
    const revokedSearch = { ...searchPayload, items: [unavailableProduct] };
    const revokedDetail = { ...detailPayload, product: unavailableProduct, history: { before_coupon: [], confirmed_after_coupon: [] }, history_quality: { before_coupon: { raw_sample_count: 0, daily_representatives: [], truncated: false }, confirmed_after_coupon: { raw_sample_count: 0, daily_representatives: [], truncated: false } } };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(revokedSearch, 200)).mockResolvedValueOnce(jsonResponse(revokedDetail, 200)));
    history.replaceState({}, "", "/?mode=synthetic&contract=v4"); render(<App/>);
    expect(await screen.findByText("來源權限不可用，價格與歷史必須失效。")).toBeInTheDocument();
    expect(screen.getAllByText("價格未知").length).toBeGreaterThan(0);
    expect(screen.getByText(/^沒有已確認券後 raw observation/)).toHaveTextContent("不套用可能、過期或不符資格的券價");
    expect(screen.getByRole("button", { name: "正式連結尚未核准" })).toBeDisabled();
  });

  it("recovers from an offline fetch only after explicit retry", async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValueOnce(jsonResponse(searchPayload, 200)).mockResolvedValueOnce(jsonResponse(detailPayload, 200));
    vi.stubGlobal("fetch", fetchMock); history.replaceState({}, "", "/?mode=synthetic&contract=v4"); render(<App/>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Failed to fetch/);
    expect(screen.queryByText("B10 Synthetic coupon item")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重試 API" }));
    expect(await screen.findByText("B10 Synthetic coupon item")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });
});
