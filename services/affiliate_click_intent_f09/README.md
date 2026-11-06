# F09 exact-price identity inert CTA adapter

F09 maps the exact synthetic A11/B11 product snapshot into a review-only click
intent.  It preserves product, SKU, seller, condition and package identity and
requires separately supplied explicit variant evidence.  B11 and A11 do not
contain `variant_id`, so their ordinary output fails closed with
`VARIANT_ID_REQUIRED`.

The result deliberately separates a general product-page reference from a
verified affiliate-link action.  Both actions are always disabled and both URL
fields are always `null`.  A normal product URL, coupon state, source permission
or contract fixture is never treated as Taiwan affiliate authority.

Only synthetic `.invalid` references are accepted by tests.  The module has no
HTTP client, browser integration, environment loader, redirect follower,
database writer, link generator, deployment path or shopping operation.

