export const B10_WIRE_SCHEMA = "CDH-COUPON-PRICE-V4" as const;

export type B10DisplayBasis = "CONFIRMED_COUPON" | "BASE_PRICE" | "PRICE_UNAVAILABLE";
export type B10CouponStatus = "CONFIRMED_APPLICABLE" | "CLAIM_REQUIRED" | "UNVERIFIED" | "INELIGIBLE" | "EXPIRED" | "UNKNOWN" | "NONE";

export interface B10SeriesIdentity {
  platform: "COUPANG_TW";
  product_id: string;
  sku_id: string;
  seller_id: string;
  condition: string;
  package_signature: string;
}

export interface B10Coupon {
  coupon_id: string | null;
  status: B10CouponStatus;
  discount_twd: number | null;
  discount_scope: "UNIT" | "ORDER_TOTAL" | "NONE";
  already_included_in_base: boolean;
  eligibility_profile: string | null;
  valid_from: string | null;
  valid_until: string | null;
  scope_evidence: string | null;
  pre_coupon_comparison_source: string | null;
  evaluation_reasons: string[];
}

export interface B10SourcePermission {
  allowed: boolean;
  state: string;
  reason: string;
}

export interface B10Product {
  series_key: string;
  title: string;
  series_identity: B10SeriesIdentity;
  data_classification: "SYNTHETIC_FIXTURE";
  source_id: string | null;
  observed_at: string | null;
  base_price_twd: number | null;
  before_coupon_price_twd: number | null;
  coupon: B10Coupon;
  confirmed_coupon_price_twd: number | null;
  possible_coupon_price_twd: number | null;
  display_price_twd: number | null;
  display_basis: B10DisplayBasis;
  minimum_purchase_quantity: number;
  minimum_item_spend_twd: number | null;
  shipping_status: string;
  required_total_twd: number | null;
  source_permission: B10SourcePermission;
  quality_flags: string[];
}

export interface B10BeforeHistoryPoint {
  observed_at: string;
  price_twd: number;
  source_id: string;
  comparison_source: string;
  series_key: string;
}

export interface B10AfterHistoryPoint {
  observed_at: string;
  price_twd: number;
  coupon_id: string;
  eligibility_profile: string;
  source_id: string;
  scope_evidence: string;
  series_key: string;
}

export interface B10DailyRepresentative {
  taipei_date: string;
  representative_price_twd: number;
  sample_count: number;
}

export interface B10HistoryQuality {
  raw_sample_count: number;
  daily_representatives: B10DailyRepresentative[];
  truncated: boolean;
}

export interface B10SearchResponse {
  schema_version: typeof B10_WIRE_SCHEMA;
  data_classification: "SYNTHETIC_FIXTURE";
  items: B10Product[];
  page: number;
  limit: number;
  total: number;
  data_version: string;
}

export interface B10DetailResponse {
  schema_version: typeof B10_WIRE_SCHEMA;
  data_classification: "SYNTHETIC_FIXTURE";
  product: B10Product;
  history: { before_coupon: B10BeforeHistoryPoint[]; confirmed_after_coupon: B10AfterHistoryPoint[] };
  history_quality: { before_coupon: B10HistoryQuality; confirmed_after_coupon: B10HistoryQuality };
  data_version: string;
}
