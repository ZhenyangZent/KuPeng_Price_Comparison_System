import type { CouponPriceResponse, CouponStatus } from "./couponTypes";

const statusLabels: Record<CouponStatus, string> = {
  CONFIRMED_APPLICABLE: "已確認適用",
  CLAIM_REQUIRED: "需先領券，尚未確認",
  UNVERIFIED: "優惠資格未驗證",
  INELIGIBLE: "目前資格不適用",
  EXPIRED: "優惠券已過期",
  UNKNOWN: "優惠券條件未知",
  NONE: "未提供優惠券"
};

export interface CouponPriceView {
  primaryPrice: number | null;
  primaryLabel: "已確認券後商品價" | "券前商品價" | "價格未知";
  basePrice: number | null;
  possiblePrice: number | null;
  statusLabel: string;
  confirmed: boolean;
  checkoutTotalKnown: boolean;
}

export function toCouponPriceView(value: CouponPriceResponse): CouponPriceView {
  const confirmed = value.display_basis === "CONFIRMED_COUPON";
  return {
    primaryPrice: value.display_price_twd,
    primaryLabel: confirmed ? "已確認券後商品價" : value.display_basis === "BASE_PRICE" ? "券前商品價" : "價格未知",
    basePrice: value.base_price_twd,
    possiblePrice: value.possible_coupon_price_twd,
    statusLabel: statusLabels[value.coupon.status],
    confirmed,
    checkoutTotalKnown: value.required_total_twd !== null
  };
}
