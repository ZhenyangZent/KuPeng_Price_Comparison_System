# G03 CI preview (inactive)

These files are review-only examples for a future private CI service. They are deliberately outside `.github/workflows` and are not active automation.

Both examples require the four hash-bound review ZIPs and a pre-provisioned dependency cache. They forbid dependency installation, external deployment, product collection, notification and real affiliate clicks. A missing dependency is reported as `NOT_EXECUTED_DEPENDENCY` with remediation guidance.

The Linux preview expects `google-chrome`, `chromium` or `chromium-browser`. The Windows preview expects Chrome at the normal Program Files location. Headless execution uses A06's loopback-only stub and disables background networking; it does not focus or operate the user's desktop browser.
