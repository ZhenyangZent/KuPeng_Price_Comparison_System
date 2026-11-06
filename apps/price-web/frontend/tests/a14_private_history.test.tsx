import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PrivateHistoryBrowser } from "../src/PrivateHistoryBrowser";

const key = "a".repeat(64);
const identity = { platform: "COUPANG_TW", product_id: "P-A14-REOPEN", sku_id: "SKU-A14-REOPEN", seller_id: "SELLER-A14", condition: "NEW", package_signature: "EACH-1", currency: "TWD" };
const product = { series_key: key, title: "A14 私人歷史商品", source_id: "OBS-B15-2", observed_at: "2026-11-04T04:00:00Z", display_price_twd: 950, display_basis: "USER_ENTERED_BEFORE_COUPON", before_coupon_price_twd: 950, confirmed_coupon_price_twd: null, possible_coupon_price_twd: null, required_total_twd: null, data_classification: "PRIVATE_LOCAL_USER_ENTERED", cta_enabled: false, click_url: null, series_identity: identity, source_permission: { allowed: true, state: "PRIVATE_LOCAL_ONLY", reason: "USER_EXPLICITLY_CONFIRMED_LOCAL_STORAGE" } };
const point = (date: string, price: number, id: string) => ({ observed_at: `${date}T04:00:00Z`, taipei_date: date, price_twd: price, series_key: key, source_id: id });
const daily = (date: string, price: number) => ({ taipei_date: date, representative_price_twd: price, sample_count: 1 });
const search = { schema_version: "CDH-PRIVATE-PRICE-V1", data_classification: "PRIVATE_LOCAL_USER_ENTERED", data_version: "private-v2", page: 1, limit: 20, total: 1, items: [product] };
const detail = { schema_version: "CDH-PRIVATE-PRICE-V1", data_classification: "PRIVATE_LOCAL_USER_ENTERED", data_version: "private-v2", product, history: { before_coupon: [point("2026-11-03", 1000, "OBS-B15-1"), point("2026-11-04", 950, "OBS-B15-2")], confirmed_after_coupon: [], user_reported_after_coupon: [{ ...point("2026-11-03", 900, "OBS-B15-1"), eligibility: "UNKNOWN", evidence_level: "NONE", platform_verified: false }] }, history_quality: { before_coupon: { raw_sample_count: 2, truncated: false, daily_representatives: [daily("2026-11-03", 1000), daily("2026-11-04", 950)] }, confirmed_after_coupon: { raw_sample_count: 0, truncated: false, daily_representatives: [] }, user_reported_after_coupon: { raw_sample_count: 1, truncated: false, daily_representatives: [daily("2026-11-03", 900)] } } };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("A14 saved private history browser", () => {
  it.each(["A14 私人歷史商品", "P-A14-REOPEN", "SKU-A14-REOPEN"])("searches read-only by %s and loads the three exact tracks", async (query) => {
    const fetchMock = vi.fn().mockResolvedValueOnce(json(search)).mockResolvedValueOnce(json(detail));
    vi.stubGlobal("fetch", fetchMock);
    render(<PrivateHistoryBrowser/>);
    fireEvent.change(screen.getByLabelText("名稱、商品 ID 或 SKU"), { target: { value: query } });
    fireEvent.click(screen.getByRole("button", { name: "搜尋私人紀錄" }));
    const result = await screen.findByRole("button", { name: /A14 私人歷史商品/ });
    expect(result).toHaveTextContent("PRIVATE LOCAL");
    expect(result).toHaveTextContent("P-A14-REOPEN · SKU-A14-REOPEN");
    fireEvent.click(result);
    const container = await screen.findByRole("region", { name: "私人商品歷史明細" });
    const before = within(container).getByRole("region", { name: "券前歷史" });
    const confirmed = within(container).getByRole("region", { name: "已確認券後歷史" });
    const reported = within(container).getByRole("region", { name: "使用者自報券後歷史" });
    expect(before.querySelectorAll("[data-history-granularity=raw] .history-row")).toHaveLength(2);
    expect(before.querySelectorAll("[data-history-granularity=daily] .history-row")).toHaveLength(2);
    expect(confirmed).toHaveTextContent("沒有資料；不以零元或其他軌跡補值");
    expect(reported.querySelectorAll("[data-history-granularity=raw] .history-row")).toHaveLength(1);
    expect(container).toHaveTextContent("PRIVATE_LOCAL_USER_ENTERED");
    expect(container).toHaveTextContent("NOT PLATFORM VERIFIED");
    expect(within(container).getByRole("button", { name: "正式分潤連結尚未核准" })).toBeDisabled();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(String(fetchMock.mock.calls[0][0])).toContain(`/products?q=${encodeURIComponent(query)}`);
    expect(fetchMock.mock.calls.every((call) => !call[1]?.method || call[1]?.method === "GET")).toBe(true);
  });

  it("fails closed without mixing synthetic fallback data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ error: { code: "B15_UNAVAILABLE" } }, 503)));
    render(<PrivateHistoryBrowser/>);
    fireEvent.change(screen.getByLabelText("名稱、商品 ID 或 SKU"), { target: { value: "P-A14-REOPEN" } });
    fireEvent.click(screen.getByRole("button", { name: "搜尋私人紀錄" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("B15_UNAVAILABLE");
    expect(screen.queryByRole("button", { name: /A14 私人歷史商品/ })).not.toBeInTheDocument();
  });
});
