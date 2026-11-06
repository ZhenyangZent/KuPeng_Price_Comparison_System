# Pinned B10 upstream

- Source archive: `review/releases/CDH_B_R06_001_REVIEW.zip`
- Source archive SHA-256: `dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549`
- Imported subtree: `CDH_B_R06_001_REVIEW/services/price_coupon_v4`
- Purpose: reproducible A10 integration testing against the exact accepted B10 release, without depending on a concurrently changing B worktree.
- Mutation policy: immutable upstream input; A10 does not modify these files.

The package verifier compares this subtree byte-for-byte with the matching entries in the pinned B10 archive before delivery.
