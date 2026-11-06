export const COUPON_SCHEMA_VERSION = "CDH-COUPON-PRICE-V4" as const;

export type CouponStatus =
  | "CONFIRMED_APPLICABLE"
  | "CLAIM_REQUIRED"
  | "UNVERIFIED"
  | "INELIGIBLE"
  | "EXPIRED"
  | "UNKNOWN"
  | "NONE";

export type CouponDisplayBasis = "CONFIRMED_COUPON" | "BASE_PRICE" | "UNAVAILABLE";

export interface CouponSeriesIdentity {
  platform: "COUPANG_TW";
  product_id: string;
  sku_id: string;
  seller_id: string;
  condition: "NEW";
  package_signature: string;
}

export interface CouponEvidence {
  coupon_id: string | null;
  status: CouponStatus;
  discount_twd: number | null;
  already_included_in_base: boolean;
  eligibility_profile: string | null;
  valid_from: string | null;
  valid_until: string | null;
  scope_evidence: string | null;
}

export interface CouponHistoryPoint {
  observed_at: string;
  price_twd: number;
  product_id: string;
  sku_id: string;
  seller_id: string;
  coupon_id: string | null;
  eligibility_profile: string | null;
  source_id: string;
  source_evidence: string;
}

export interface CouponHistory {
  before_coupon: CouponHistoryPoint[];
  confirmed_after_coupon: CouponHistoryPoint[];
}

export interface CouponPriceResponse {
  schema_version: typeof COUPON_SCHEMA_VERSION;
  series_identity: CouponSeriesIdentity;
  data_classification: "SYNTHETIC_FIXTURE";
  source_id: string;
  observed_at: string;
  base_price_twd: number | null;
  coupon: CouponEvidence;
  confirmed_coupon_price_twd: number | null;
  possible_coupon_price_twd: number | null;
  display_price_twd: number | null;
  display_basis: CouponDisplayBasis;
  shipping_status: "FREE" | "PAID" | "UNKNOWN";
  required_total_twd: number | null;
  price_basis: {
    amount_basis: "PER_ITEM";
    quantity: 1;
    coupon_discount_basis: "PER_ITEM";
  };
  history: CouponHistory;
}
