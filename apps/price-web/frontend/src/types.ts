export const SCHEMA_VERSION = "CDH-WEB-CONTRACT-V2" as const;
export type DataMode = "LOCAL_API" | "SYNTHETIC_DEMO";
export type DataSourceStatus = "USER_RECORDED_ONLY" | "SYNTHETIC_FIXTURE_ONLY";
export type DataClassification = "USER_RECORDED" | "SYNTHETIC_DEMO_ONLY";
export type ShippingStatus = "FREE" | "PAID" | "UNKNOWN";
export type StockStatus = "IN_STOCK" | "OUT_OF_STOCK" | "UNKNOWN";
export type CoverageStatus = "NONE" | "LOW" | "PARTIAL" | "COMPLETE";
export type PriceBasis = "GENERAL_OBSERVED" | "UNAVAILABLE";
export type SourceType = "USER_ENTERED" | "USER_FILE" | "SYNTHETIC";
export type AffiliateState = "UNCONFIGURED" | "PENDING_OFFICIAL_DOCS" | "VERIFIED" | "FAILED" | "DISABLED";
export interface CoverageWindow { sample_days: number; status: CoverageStatus }
export interface Coverage { basis: "COMPLETED_CALENDAR_DAYS"; timezone: "Asia/Taipei"; m7: CoverageWindow; m30: CoverageWindow; m90: CoverageWindow }
export interface ProductSummary {
  id: string; title: string; variant_signature: string;
  last_observed_price_twd: number | null; last_observed_at: string | null;
  observed_days: number; sample_days_m7: number; sample_days_m30: number; sample_days_m90: number;
  coverage: Coverage; shipping_status: ShippingStatus; stock_status: StockStatus;
  price_basis: PriceBasis; source_price_basis: string | null; identity_state: "EXACT" | "INCOMPLETE";
  quality_flags: string[]; thumbnail: null;
}
export interface Offer {
  offer_id: string; seller_id: string | null; sku_id: string | null; product_id: string | null;
  minimum_purchase_quantity: number | null; item_condition: "UNKNOWN"; item_condition_source: "NOT_RECORDED";
  price_basis: PriceBasis; source_price_basis: string | null; identity_state: "EXACT" | "INCOMPLETE";
}
export interface HistoryPoint { observed_at: string; price_twd: number; source_type: SourceType; source_id: string | null }
export interface AffiliateInfo {
  state: AffiliateState; click_url: string | null; verified_product_match: boolean; bound_product_id: string | null;
  bound_sku_id?: string | null; provider_id?: string | null; official_host_verified?: boolean;
  verified_variant_match?: boolean; verified_seller_match?: boolean; valid_from?: string | null;
  valid_until?: string | null; tw_disclosure?: string | null;
}
interface V2Envelope {
  schema_version: typeof SCHEMA_VERSION; contract_compatibility: ["CDH-WEB-CONTRACT-V1"];
  data_source_status: DataSourceStatus; data_classification: DataClassification;
}
export interface SearchResponse extends V2Envelope { items: ProductSummary[]; page: number; limit: number; total: number }
export interface ProductDetailResponse extends V2Envelope {
  product: ProductSummary; offers: Offer[]; history: HistoryPoint[];
  observation_period_min_twd: number | null; observation_period_label: "觀測期間最低價"; affiliate: AffiliateInfo;
}
export interface AffiliateResponse extends V2Envelope { product_id: string; affiliate: AffiliateInfo }
export interface PriceDataClient {
  readonly mode: DataMode;
  searchProducts(query: string, page?: number, limit?: number, signal?: AbortSignal): Promise<SearchResponse>;
  getProductDetail(productId: string, signal?: AbortSignal): Promise<ProductDetailResponse>;
}
