# Coupang Deal Hunter｜R10 工作線狀態

UPDATED_LOCAL_DATE: `2026-11-05`
SOURCE_BUNDLE_SHA256: `0474031243db86ffc7c7b05e7569f701f5705cf84a25b98453b987f1c99b7abc`

| Role | Task ID | State | Evidence boundary |
|---|---|---|---|
| A | `CDH-A12-LOCAL-PRICE-DAILY-DOM-AND-SAFE-IMPORT-PREVIEW-001` | `AUTHORIZED_NEW_VALIDATION_REQUIRED` | A11 received/archived；daily raw/representative DOM still needs same-version proof |
| B | `CDH-B14-STRICT-JSON-INGRESS-AND-DRYRUN-001` | `AUTHORIZED_REWORK_P1` | B13 duplicate JSON key last-wins reproduced；must fail closed before parsing |
| C | `CDH-C11-PROVENANCE-B13-B14-PREVIEW-CONSUMPTION-001` | `AUTHORIZED_SOURCE_BLOCKED` | synthetic/manual preview only；B14 exact input required for final binding |
| D | `CDH-D11-B14-P1-AND-A11-INTEGRATION-SECURITY-001` | `AUTHORIZED_NEW_UPSTREAM_REQUIRED` | independent review only；must not modify A/B source |
| E | `CDH-E11-R09-EIGHT-EXACT-ACK-AND-LIVE-QUEUE-001` | `PENDING_UPLOAD` | E11 SHA `ef4489d55b69d7fc24d5965040c3e88f263847e8d2a9c64ca8a4a4055ddec70e`；receipt is not functional PASS |
| F | `CDH-F09-EXACT-PRICE-IDENTITY-INERT-CTA-ADAPTER-001` | `AUTHORIZED_CTA_DISABLED` | official Taiwan product-specific affiliate evidence remains unavailable |
| G | `CDH-G09-A11-DOM-AND-B14-SAFE-IMPORT-CI-001` | `AUTHORIZED_NEW_UPSTREAM_REQUIRED` | A11 daily DOM and B14 exact release require new evidence |
| H | `CDH-H08-A11-B11-DAILY-DOM-AND-LAUNCHER-JOURNEY-001` | `AUTHORIZED_NEW_VALIDATION_REQUIRED` | H07 evidence PASS but product integration FAIL remains preserved |

R09 eight ACKs are `RECEIVED_ACK_ARCHIVED` only. Central R09 portable tests were 232/232, but B13 remains P1 rework and H07 remains product integration fail. Source, affiliate, deployment, and transaction gates remain closed.
