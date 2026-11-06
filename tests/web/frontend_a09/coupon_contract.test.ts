import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { COUPON_FIXTURES } from "../../../apps/price-web/frontend/src/couponFixtures";
import { parseCouponPriceV4, strictIsoTimestamp } from "../../../apps/price-web/frontend/src/couponRuntimeSchema";

describe("A09 role-path coupon and CSP gates", () => {
  it("parses all canonical synthetic V4 fixtures", () => {
    expect(COUPON_FIXTURES.map((fixture) => parseCouponPriceV4(fixture).schema_version)).toEqual(Array(5).fill("CDH-COUPON-PRICE-V4"));
  });

  it("distinguishes confirmed zero from unknown null", () => {
    const zero = COUPON_FIXTURES.find((fixture) => fixture.confirmed_coupon_price_twd === 0)!;
    const unknown = COUPON_FIXTURES.find((fixture) => fixture.display_basis === "UNAVAILABLE")!;
    expect(parseCouponPriceV4(zero).display_price_twd).toBe(0);
    expect(parseCouponPriceV4(unknown).display_price_twd).toBeNull();
  });

  it("fixes the A08 T010 regression and rejects it at the boundary", () => {
    const fixtures = readFileSync(path.resolve("apps/price-web/frontend/src/fixtures.ts"), "utf8");
    expect(fixtures).not.toContain("T0${i+8}");
    expect(() => strictIsoTimestamp("2026-11-01T010:00:00Z", "observed_at")).toThrow(/嚴格 ISO/);
  });

  it("ships a restrictive CSP without wildcard or unsafe-inline bypasses", () => {
    const html = readFileSync(path.resolve("apps/price-web/frontend/index.html"), "utf8");
    const config = readFileSync(path.resolve("apps/price-web/frontend/vite.config.ts"), "utf8");
    expect(html).toContain("Content-Security-Policy");
    expect(config).toContain("Content-Security-Policy");
    expect(`${html}\n${config}`).not.toMatch(/unsafe-inline|unsafe-eval/);
    expect(`${html}\n${config}`).not.toMatch(/(?:^|[;\s])\*(?:[;\s]|$)/);
    expect(html).toContain("object-src 'none'");
    expect(html).toContain("base-uri 'none'");
  });
});
