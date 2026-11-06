import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "../src/App";
import { COUPON_FIXTURES } from "../src/couponFixtures";
import { CouponContractError, parseCouponPriceV4, strictIsoTimestamp } from "../src/couponRuntimeSchema";
import { toCouponPriceView } from "../src/couponUiAdapter";

const confirmed = COUPON_FIXTURES.find((item) => item.coupon.status === "CONFIRMED_APPLICABLE" && item.confirmed_coupon_price_twd === 49)!;
const claimRequired = COUPON_FIXTURES.find((item) => item.coupon.status === "CLAIM_REQUIRED")!;
const expired = COUPON_FIXTURES.find((item) => item.coupon.status === "EXPIRED")!;

describe("A09 coupon-first V4 contract", () => {
  it("accepts strict ISO timestamps and rejects malformed or impossible dates", () => {
    expect(strictIsoTimestamp("2026-11-05T10:00:00+08:00", "t")).toBe("2026-11-05T10:00:00+08:00");
    expect(() => strictIsoTimestamp("2026-11-01T010:00:00Z", "t")).toThrow(/嚴格 ISO/);
    expect(() => strictIsoTimestamp("2026-02-30T10:00:00Z", "t")).toThrow(/日曆時間/);
  });

  it("makes the confirmed coupon price primary while preserving base price", () => {
    const parsed = parseCouponPriceV4(confirmed);
    expect(toCouponPriceView(parsed)).toMatchObject({ primaryPrice: 49, basePrice: 99, confirmed: true });
    expect(parsed.history.before_coupon).toHaveLength(2);
    expect(parsed.history.confirmed_after_coupon).toHaveLength(2);
  });

  it.each([claimRequired, expired])("keeps non-confirmed coupon status out of the primary price", (fixture) => {
    const parsed = parseCouponPriceV4(fixture);
    expect(parsed.confirmed_coupon_price_twd).toBeNull();
    expect(parsed.display_price_twd).toBe(parsed.base_price_twd);
    expect(toCouponPriceView(parsed).confirmed).toBe(false);
  });

  it("does not subtract an already included coupon twice", () => {
    const included = {
      ...confirmed,
      base_price_twd: 49,
      confirmed_coupon_price_twd: 49,
      display_price_twd: 49,
      coupon: { ...confirmed.coupon, already_included_in_base: true }
    };
    expect(parseCouponPriceV4(included).confirmed_coupon_price_twd).toBe(49);
    expect(() => parseCouponPriceV4({ ...included, confirmed_coupon_price_twd: 0, display_price_twd: 0 })).toThrow(/不一致/);
  });

  it("rejects cross-SKU history, expired confirmation and guessed zero", () => {
    const crossSku = structuredClone(confirmed);
    crossSku.history.confirmed_after_coupon[0].sku_id = "OTHER-SKU";
    expect(() => parseCouponPriceV4(crossSku)).toThrow(/跨商品、SKU/);
    const expiredConfirmation = { ...confirmed, observed_at: "2026-12-01T00:00:00Z" };
    expect(() => parseCouponPriceV4(expiredConfirmation)).toThrow(/有效期/);
    const unknown = COUPON_FIXTURES.find((item) => item.coupon.status === "UNKNOWN")!;
    expect(() => parseCouponPriceV4({ ...unknown, display_price_twd: 0 })).toThrow(/價格未知/);
  });

  it("rejects ambiguous multi-item price basis", () => {
    expect(() => parseCouponPriceV4({ ...confirmed, price_basis: { ...confirmed.price_basis, quantity: 2 } })).toThrow(/多件口徑/);
  });
});

describe("A09 coupon-first UI", () => {
  it("renders confirmed price, base price, dual history and disabled outbound CTA", async () => {
    history.replaceState({}, "", "/?mode=synthetic&contract=v4&source=fixture");
    render(<App/>);
    expect((await screen.findAllByText("已確認券後商品價")).length).toBeGreaterThan(0);
    expect(screen.getByText("NT$ 49", { selector: ".price-block strong" })).toBeInTheDocument();
    expect(screen.getByText(/NT\$ 99/, { selector: ".status-badge" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "券前商品價歷史" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "已確認券後商品價歷史" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "正式連結尚未核准" })).toBeDisabled();
  });

  it("labels claim-required and zero-price safety without promoting checkout total", async () => {
    history.replaceState({}, "", "/?mode=synthetic&contract=v4&source=fixture");
    render(<App/>);
    fireEvent.click(screen.getByRole("button", { name: /SYNTHETIC｜CLAIM/ }));
    expect(await screen.findByText(/可能券後價 NT\$ 75 不會作為主價/)).toBeInTheDocument();
    expect(screen.getByText("NT$ 100", { selector: ".price-block strong" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /SYNTHETIC｜ZERO/ }));
    expect(await screen.findByText(/不是零成本到手/)).toBeInTheDocument();
    expect(screen.getByText(/required_total_twd 維持 null/)).toBeInTheDocument();
  });
});
