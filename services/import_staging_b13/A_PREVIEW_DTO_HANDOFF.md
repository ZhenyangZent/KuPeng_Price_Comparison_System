# Future A-line preview DTO handoff

A may consume only the versioned `CDH-B13-DRYRUN-PREVIEW-DTO-1` or paginated `CDH-B13-PREVIEW-STATUS-1` response in a separately authorized task.

Recommended UI mapping:

- summary cards: accepted, invalid, denied, duplicate and conflict counts;
- row table: record ID, exact identity, observation UTC, bounded source evidence, status and `field_errors`;
- history candidate: identity key, source observation time, before-coupon and confirmed coupon prices;
- safety banner: preview only, writes 0, live source blocked, CTA disabled.

This document does not authorize A source changes. Do not display the preview as imported history and do not offer an “approve/write” control until a separately versioned canonical-import contract is authorized.
