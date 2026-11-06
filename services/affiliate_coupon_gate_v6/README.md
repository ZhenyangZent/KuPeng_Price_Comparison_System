# F06 B10 wire-aware coupon gate

`affiliate_coupon_gate_v6` consumes the exact B10 `CDH-COUPON-PRICE-V4` Search or Detail envelope. The adapter enforces exact envelope/product shapes, synthetic classification, six-part series identity, source permission, coupon scope and validity evidence, minimum quantity math, already-included comparison evidence, and separate before/confirmed-after history tracks.

The adapter is pure and has no HTTP client. Integration tests call the exact SHA-bound B10 WSGI app in process and then pass its real JSON response to F06. R07 provides no affiliate authorization: all decisions remain `SOURCE_AUTHORIZATION_REQUIRED`, `cta_enabled=false`, and `click_url=null`, regardless of coupon state or positive-looking trust inputs.

No `.env` loader, browser, external host, network API, deployment, notification, claim, cart, order, or payment action exists in this module.
