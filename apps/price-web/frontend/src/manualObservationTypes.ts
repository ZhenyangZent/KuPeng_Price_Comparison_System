export type CouponEligibility = "UNKNOWN" | "USER_ASSERTED_ELIGIBLE";
export type CouponEvidenceLevel = "NONE" | "USER_DESCRIPTION" | "USER_LOCAL_REFERENCE";

export interface ManualObservationDraft {
  title: string; product_id: string; sku_id: string; seller_id: string; package_signature: string;
  observed_at: string; quantity: number; before_coupon_price_twd: number;
  user_reported_coupon_price_twd: number | null; coupon_eligibility: CouponEligibility;
  coupon_evidence_level: CouponEvidenceLevel; coupon_evidence_note: string; source_note: string;
}

export interface ManualObservationRequest {
  schema_version: "CDH-B15-MANUAL-OBSERVATION-1"; submission_id: string; title: string;
  identity: { platform: "COUPANG_TW"; product_id: string; sku_id: string; seller_id: string; condition: "NEW"; package_signature: string; currency: "TWD" };
  observed_at: string; quantity: number; before_coupon_price_twd: number;
  user_reported_coupon: { status: "NONE" | "USER_REPORTED"; price_twd: number | null; eligibility: CouponEligibility; evidence_level: CouponEvidenceLevel; evidence_note: string | null; valid_from: null; valid_until: null };
  shipping: { status: "UNKNOWN"; shipping_fee_twd: null; mandatory_fee_twd: null };
  source: { source_class: "USER_ENTERED"; visibility: "PRIVATE_LOCAL"; note: string };
}

export interface ManualSession {
  schema_version: "CDH-B15-PRIVATE-OBSERVATION-API-1"; csrf_token: string; storage_scope: "PRIVATE_LOCAL_ONLY";
  baselines: { B11: string; B14: string; C11_REV2: string } | { B13: string; B14: string; C11_REV2: string; B15_REV2: string; A14: string };
}

export interface ManualPreview {
  schema_version: "CDH-B15-PRIVATE-OBSERVATION-API-1"; mode: "PREVIEW_NO_DATABASE_WRITE";
  preview_id: string; confirm_token: string; expires_in_seconds: number;
  will_save: Record<string, unknown> & { series_key: string; observed_at: string; before_coupon_price_twd: number; confirmed_after_coupon_price_twd: null; required_total_twd: number | null; identity: ManualObservationRequest["identity"]; user_reported_coupon: ManualObservationRequest["user_reported_coupon"]; source: { source_class: "USER_ENTERED"; visibility: "PRIVATE_LOCAL"; platform_verified: false; note: string } };
  warnings: string[]; database_write_count: 0;
}

export interface ManualCommit {
  schema_version: "CDH-B15-PRIVATE-OBSERVATION-API-1"; status: "SAVED_PRIVATE_LOCAL";
  observation_id: string; series_key: string; idempotent_replay: boolean; backup_created: boolean; backup_cleanup_removed_count: number; data_version: string;
}

export interface PrivateHistoryPoint { observed_at: string; taipei_date: string; price_twd: number; series_key: string; source_id: string; eligibility?: string; evidence_level?: string; platform_verified?: false }
export interface PrivateDailyPoint { taipei_date: string; representative_price_twd: number; sample_count: number }
export interface PrivateTrackQuality { raw_sample_count: number; truncated: boolean; daily_representatives: PrivateDailyPoint[] }
export interface PrivateProduct { series_key: string; title: string; observed_at: string; display_price_twd: number; before_coupon_price_twd: number; confirmed_coupon_price_twd: null; possible_coupon_price_twd: number | null; required_total_twd: number | null; data_classification: "PRIVATE_LOCAL_USER_ENTERED"; cta_enabled: false; click_url: null; series_identity: ManualObservationRequest["identity"]; source_permission: { allowed: true; state: "PRIVATE_LOCAL_ONLY"; reason: "USER_EXPLICITLY_CONFIRMED_LOCAL_STORAGE" } }
export interface PrivateSearch { schema_version: "CDH-PRIVATE-PRICE-V1"; data_classification: "PRIVATE_LOCAL_USER_ENTERED"; data_version: string; page: number; limit: number; total: number; items: PrivateProduct[] }
export interface PrivateDetail { schema_version: "CDH-PRIVATE-PRICE-V1"; data_classification: "PRIVATE_LOCAL_USER_ENTERED"; data_version: string; product: PrivateProduct; history: { before_coupon: PrivateHistoryPoint[]; confirmed_after_coupon: PrivateHistoryPoint[]; user_reported_after_coupon: PrivateHistoryPoint[] }; history_quality: { before_coupon: PrivateTrackQuality; confirmed_after_coupon: PrivateTrackQuality; user_reported_after_coupon: PrivateTrackQuality } }
