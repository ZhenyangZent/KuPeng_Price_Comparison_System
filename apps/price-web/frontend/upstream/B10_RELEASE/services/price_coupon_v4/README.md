# B10 coupon price readmodel

This isolated, standard-library-only service implements opt-in `CDH-COUPON-PRICE-V4` over a SHA-bound synthetic SQLite snapshot opened with `mode=ro` and `PRAGMA query_only=ON`.

The primary display price uses a stored, evidence-checked confirmed coupon price only when product, SKU, seller, observation time, current validity and eligibility profile all match. Other coupon states never alter the main price. Valid base price is the fallback; otherwise the result is `PRICE_UNAVAILABLE`.

Before-coupon and confirmed-after-coupon raw histories are separate. Each also exposes completed Taipei-day representative prices and sample counts. Historical applicability is evaluated at each observation time, so a current coupon is never backfilled into older observations.

The service is synthetic/offline only. It does not read `.env`, user databases, browsers or external websites and does not claim, click or redeem coupons.
