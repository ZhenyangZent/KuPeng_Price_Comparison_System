# A13 integration handoff

A13 must call the B15 loopback API without fixture or mock fallback. Fetch the session first, submit the manual observation to preview, show `will_save` and all warnings, then send confirm only after the user clicks the confirmation control.

Render `history.before_coupon`, `history.confirmed_after_coupon`, and `history.user_reported_after_coupon` as distinct tracks. The confirmed track will be empty for manual B15 observations. Label all results `PRIVATE_LOCAL_USER_ENTERED / NOT_PLATFORM_VERIFIED`, retain unknown shipping and totals as null, and keep CTA disabled with null click URL.
