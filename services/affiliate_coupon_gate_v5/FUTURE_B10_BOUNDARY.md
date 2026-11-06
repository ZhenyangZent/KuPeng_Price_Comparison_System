# Future B10 opt-in boundary candidate

STATUS: `CANDIDATE_FOR_CROSSLINE_REVIEW`

F05 consumes the frozen `CDH-COUPON-PRICE-V4` shape only as an independent opt-in sidecar. It does not modify V2 Search/Detail/Affiliate or V3 quality fields. The B10 producer remains responsible for coupon evidence, price/history semantics and exact series identity; F05 rechecks current applicability, identity, eligibility, time and arithmetic before composing a price decision.

Affiliate authority flows only from the authenticated F04 decision plus the independently loaded C06 runtime ceiling. Coupon fields, histories, display price, source ID and evidence cannot enable CTA and cannot provide a URL. A/B integration requires a later read-only sidecar contract review after B10 exists.

Current output remains `SOURCE_AUTHORIZATION_REQUIRED`, `click_url=null`, `cta_enabled=false`. No endpoint is defined here.
