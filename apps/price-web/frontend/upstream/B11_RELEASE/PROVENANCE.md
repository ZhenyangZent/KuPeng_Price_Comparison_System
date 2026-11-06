# Pinned B11 upstream

- Source archive: `review/releases/CDH_B_R07_001_REVIEW.zip`
- Source archive SHA-256: `6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a`
- Review manifest SHA-256: `ebb3deb67f872e998c92830288f2d3eccb9c8fcc60c713a9fa60fe0d6d95be64`
- Imported subtree: `CDH_B_R07_001_REVIEW/services/price_coupon_v4`
- Purpose: reproducible A10 integration testing against the exact B11 R07 candidate release.
- Mutation policy: immutable upstream input; A10 does not modify these files.

The B11 review manifest declared 73 payloads and validation found missing/size/hash mismatch `0/0/0`; ZIP safe-path, duplicate-path and CRC gates also passed.
