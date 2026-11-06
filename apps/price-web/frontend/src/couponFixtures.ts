import { parseCouponPriceV4 } from "./couponRuntimeSchema";
import { COUPON_SCHEMA_VERSION, type CouponPriceResponse, type CouponStatus } from "./couponTypes";

const identity = (suffix: string) => ({
  platform: "COUPANG_TW" as const,
  product_id: `SYN-P-${suffix}`,
  sku_id: `SYN-SKU-${suffix}`,
  seller_id: `SYN-SELLER-${suffix}`,
  condition: "NEW" as const,
  package_signature: "1x100ml"
});
const point = (series: ReturnType<typeof identity>, observed_at: string, price_twd: number, source_id: string, coupon_id: string | null = null) => ({
  observed_at, price_twd, product_id: series.product_id, sku_id: series.sku_id, seller_id: series.seller_id,
  coupon_id, eligibility_profile: coupon_id ? "SYN-ELIGIBLE-PROFILE" : null, source_id, source_evidence: `SYN-EVIDENCE-${source_id}`
});
function fixture(suffix: string, status: CouponStatus, base: number | null, discount: number | null, confirmed: number | null, possible: number | null): CouponPriceResponse {
  const series = identity(suffix), hasCoupon = status !== "NONE";
  const raw = {
    schema_version: COUPON_SCHEMA_VERSION,
    series_identity: series,
    data_classification: "SYNTHETIC_FIXTURE",
    source_id: `SYN-SOURCE-${suffix}`,
    observed_at: "2026-11-05T00:00:00Z",
    base_price_twd: base,
    coupon: {
      coupon_id: hasCoupon ? `SYN-COUPON-${suffix}` : null,
      status,
      discount_twd: discount,
      already_included_in_base: false,
      eligibility_profile: hasCoupon ? "SYN-ELIGIBLE-PROFILE" : null,
      valid_from: hasCoupon ? "2026-11-01T00:00:00Z" : null,
      valid_until: status === "EXPIRED" ? "2026-11-04T23:59:59Z" : hasCoupon ? "2026-11-30T23:59:59Z" : null,
      scope_evidence: hasCoupon ? `SYN-SCOPE-${suffix}` : null
    },
    confirmed_coupon_price_twd: confirmed,
    possible_coupon_price_twd: possible,
    display_price_twd: confirmed ?? base,
    display_basis: confirmed !== null ? "CONFIRMED_COUPON" : base !== null ? "BASE_PRICE" : "UNAVAILABLE",
    shipping_status: "UNKNOWN",
    required_total_twd: null,
    price_basis: { amount_basis: "PER_ITEM", quantity: 1, coupon_discount_basis: "PER_ITEM" },
    history: {
      before_coupon: base === null ? [] : [
        point(series, "2026-11-03T08:00:00Z", base + 30, `BASE-${suffix}-1`),
        point(series, "2026-11-05T00:00:00Z", base, `BASE-${suffix}-2`)
      ],
      confirmed_after_coupon: confirmed === null ? [] : [
        point(series, "2026-11-03T08:00:00Z", confirmed + 30, `COUPON-${suffix}-1`, `SYN-COUPON-${suffix}`),
        point(series, "2026-11-05T00:00:00Z", confirmed, `COUPON-${suffix}-2`, `SYN-COUPON-${suffix}`)
      ]
    }
  };
  return parseCouponPriceV4(raw);
}

export const COUPON_FIXTURES = [
  fixture("CONFIRMED", "CONFIRMED_APPLICABLE", 99, 50, 49, null),
  fixture("CLAIM", "CLAIM_REQUIRED", 100, 25, null, 75),
  fixture("EXPIRED", "EXPIRED", 120, 40, null, null),
  fixture("ZERO", "CONFIRMED_APPLICABLE", 50, 50, 0, null),
  fixture("UNKNOWN", "UNKNOWN", null, null, null, null)
] as const;
