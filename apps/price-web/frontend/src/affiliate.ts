import type { AffiliateInfo, Offer } from "./types";

export interface AffiliatePolicy {
  approved_provider_id: string | null;
  official_hosts: readonly string[];
}

// C03/F01 have not established an applicable Taiwan provider host yet.
// Keeping this frozen list empty makes every current CTA fail closed.
export const CURRENT_AFFILIATE_POLICY: AffiliatePolicy = {
  approved_provider_id: null,
  official_hosts: []
};

export function safeAffiliateUrl(productId: string, offer: Offer | undefined, affiliate: AffiliateInfo, policy: AffiliatePolicy = CURRENT_AFFILIATE_POLICY, now = new Date()): string | null {
  if (!policy.approved_provider_id || policy.official_hosts.length === 0) return null;
  if (
    offer?.price_basis !== "GENERAL_OBSERVED" ||
    affiliate.state !== "VERIFIED" ||
    affiliate.provider_id !== policy.approved_provider_id ||
    !affiliate.official_host_verified ||
    !affiliate.verified_product_match ||
    !affiliate.verified_variant_match ||
    !affiliate.verified_seller_match ||
    affiliate.bound_product_id !== productId ||
    !offer?.sku_id ||
    affiliate.bound_sku_id !== offer.sku_id ||
    !affiliate.valid_from ||
    !affiliate.valid_until ||
    !affiliate.tw_disclosure ||
    !affiliate.click_url
  ) return null;
  const from = Date.parse(affiliate.valid_from);
  const until = Date.parse(affiliate.valid_until);
  if (!Number.isFinite(from) || !Number.isFinite(until) || from > now.getTime() || until <= now.getTime()) return null;
  try {
    const parsed = new URL(affiliate.click_url);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || !policy.official_hosts.includes(parsed.hostname.toLocaleLowerCase("en-US"))) return null;
    return parsed.toString();
  } catch {
    return null;
  }
}
