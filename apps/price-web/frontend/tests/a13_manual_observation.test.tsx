import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManualObservationPanel } from "../src/ManualObservationPanel";
import { buildManualRequest, ManualObservationClient, parseManualPreview, parsePrivateDetail } from "../src/manualObservationClient";
import type { ManualObservationDraft } from "../src/manualObservationTypes";

const key = "a".repeat(64), session = { schema_version: "CDH-B15-PRIVATE-OBSERVATION-API-1", csrf_token: "csrf-token", storage_scope: "PRIVATE_LOCAL_ONLY", baselines: { B11: "1".repeat(64), B14: "2".repeat(64), C11_REV2: "3".repeat(64) } };
const draft: ManualObservationDraft = { title: "私人測試商品", product_id: "P-A13-1", sku_id: "SKU-A13-1", seller_id: "SELLER-A13-1", package_signature: "EACH-1", observed_at: "2026-11-05T20:00:00+08:00", quantity: 1, before_coupon_price_twd: 199, user_reported_coupon_price_twd: 149, coupon_eligibility: "UNKNOWN", coupon_evidence_level: "NONE", coupon_evidence_note: "", source_note: "私人手動輸入" };
const normalized = { ...buildManualRequest(draft, "a13-request-0001"), series_key: key, observed_at: "2026-11-05T12:00:00Z", taipei_date: "2026-11-05", confirmed_after_coupon_price_twd: null, required_total_twd: null, user_reported_required_total_twd: null, input_sha256: "4".repeat(64), observation_fingerprint: "5".repeat(64), source: { source_class: "USER_ENTERED", visibility: "PRIVATE_LOCAL", note: "私人手動輸入", platform_verified: false } };
const preview = { schema_version: "CDH-B15-PRIVATE-OBSERVATION-API-1", mode: "PREVIEW_NO_DATABASE_WRITE", preview_id: "preview-id", confirm_token: "confirm-token", expires_in_seconds: 600, will_save: normalized, warnings: ["PRIVATE_USER_ENTERED", "NOT_PLATFORM_VERIFIED", "USER_REPORTED_COUPON_NOT_CONFIRMED"], database_write_count: 0 };
const commit = { schema_version: "CDH-B15-PRIVATE-OBSERVATION-API-1", status: "SAVED_PRIVATE_LOCAL", observation_id: "OBS-B15-1", series_key: key, idempotent_replay: false, backup_created: false, backup_cleanup_removed_count: 0, data_version: "private-v1" };
const product = { series_key: key, title: draft.title, observed_at: "2026-11-05T12:00:00Z", display_price_twd: 199, before_coupon_price_twd: 199, confirmed_coupon_price_twd: null, possible_coupon_price_twd: 149, required_total_twd: null, data_classification: "PRIVATE_LOCAL_USER_ENTERED", cta_enabled: false, click_url: null, series_identity: normalized.identity, source_permission: { allowed: true, state: "PRIVATE_LOCAL_ONLY", reason: "USER_EXPLICITLY_CONFIRMED_LOCAL_STORAGE" } };
const point = { observed_at: "2026-11-05T12:00:00Z", taipei_date: "2026-11-05", price_twd: 199, series_key: key, source_id: "OBS-B15-1" };
const quality = (price: number | null) => ({ raw_sample_count: price === null ? 0 : 1, truncated: false, daily_representatives: price === null ? [] : [{ taipei_date: "2026-11-05", representative_price_twd: price, sample_count: 1 }] });
const detail = { schema_version: "CDH-PRIVATE-PRICE-V1", data_classification: "PRIVATE_LOCAL_USER_ENTERED", data_version: "private-v1", product, history: { before_coupon: [point], confirmed_after_coupon: [], user_reported_after_coupon: [{ ...point, price_twd: 149, eligibility: "UNKNOWN", evidence_level: "NONE", platform_verified: false }] }, history_quality: { before_coupon: quality(199), confirmed_after_coupon: quality(null), user_reported_after_coupon: quality(149) } };
const search = { schema_version: "CDH-PRIVATE-PRICE-V1", data_classification: "PRIVATE_LOCAL_USER_ENTERED", data_version: "private-v1", page: 1, limit: 20, total: 1, items: [product] };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("A13 REV2 exact B15 adapter", () => {
  it("maps the flat form to the exact nested B15 request without elevating coupon evidence", () => {
    expect(buildManualRequest(draft, "a13-request-0001")).toEqual(expect.objectContaining({ schema_version: "CDH-B15-MANUAL-OBSERVATION-1", identity: expect.objectContaining({ package_signature: "EACH-1", condition: "NEW" }), user_reported_coupon: expect.objectContaining({ status: "USER_REPORTED", price_twd: 149, eligibility: "UNKNOWN" }), shipping: { status: "UNKNOWN", shipping_fee_twd: null, mandatory_fee_twd: null } }));
  });
  it("rejects preview writes and confirmed-coupon elevation", () => {
    expect(() => parseManualPreview({ ...preview, database_write_count: 1 })).toThrow(/不得寫入/);
    expect(() => parseManualPreview({ ...preview, will_save: { ...normalized, confirmed_after_coupon_price_twd: 149 } })).toThrow(/不得升格/);
  });
  it("rejects user-reported history if it appears as confirmed", () => {
    expect(() => parsePrivateDetail({ ...detail, history: { ...detail.history, confirmed_after_coupon: [{ ...point, price_twd: 149 }] } })).toThrow(/不得進入/);
  });
  it("obtains session CSRF before preview and uses the exact routes", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(json(session)).mockResolvedValueOnce(json(preview)); vi.stubGlobal("fetch", fetchMock);
    await new ManualObservationClient("/proxy").preview(draft, "a13-request-0001");
    expect(fetchMock).toHaveBeenCalledTimes(2); expect(String(fetchMock.mock.calls[0][0])).toBe("/proxy/api/private-observations/v1/session"); expect(String(fetchMock.mock.calls[1][0])).toBe("/proxy/api/private-observations/v1/preview"); expect(fetchMock.mock.calls[1][1]?.headers).toMatchObject({ "X-CDH-CSRF-Token": "csrf-token" });
  });
  it("fails closed when B15 is unavailable", async () => { vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("refused"))); await expect(new ManualObservationClient("/proxy").preview(draft, "a13-request-0001")).rejects.toMatchObject({ code: "B15_INPUT_UNAVAILABLE" }); });
});

describe("A13 REV2 UI", () => {
  it("requires preview and explicit confirm, then reads actual private history", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(json(session)).mockResolvedValueOnce(json(preview)).mockResolvedValueOnce(json(commit, 201)).mockResolvedValueOnce(json(search)).mockResolvedValueOnce(json(detail)); vi.stubGlobal("fetch", fetchMock); render(<ManualObservationPanel/>);
    fireEvent.click(screen.getByRole("button", { name: "開始輸入" }));
    for (const [label, value] of [["商品名稱", draft.title], ["商品 ID", draft.product_id], ["SKU／變體 ID", draft.sku_id], ["賣家 ID", draft.seller_id], ["規格簽章", draft.package_signature], ["觀測時間（含時區）", draft.observed_at]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.change(screen.getByLabelText("券前價格（TWD）"), { target: { value: "199" } }); fireEvent.change(screen.getByLabelText(/^使用者自報券後價/), { target: { value: "149" } }); fireEvent.click(screen.getByRole("button", { name: "安全預覽" }));
    expect(await screen.findByRole("region", { name: "將被保存的私人觀測預覽" })).toHaveTextContent("NT$ 149（未獨立核實）"); const button = screen.getByRole("button", { name: "確認儲存" }); expect(button).toBeDisabled(); fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(button);
    expect(await screen.findByRole("region", { name: "B15 私人歷史回讀" })).toHaveTextContent("已確認券後歷史"); expect(screen.getByRole("region", { name: "B15 私人歷史回讀" })).toHaveTextContent("沒有資料"); await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
    expect(String(fetchMock.mock.calls[2][0])).toContain("/confirm"); expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ preview_id: "preview-id", confirm_token: "confirm-token", explicit_confirm: true });
  });
});
