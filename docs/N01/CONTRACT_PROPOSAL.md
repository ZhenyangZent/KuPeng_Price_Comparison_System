# Cross-line contract proposal

Status: `PROPOSAL_ONLY`

N01 proposes the read-only adapter functions `candidate_from_c01()` and
`candidate_from_i01()`. No C01 or I01 file, database, schema or behavior is
changed.

The I01 input is accepted only when:

1. `status` is exactly `QUEUED`;
2. `scenario` is a C01 `PurchaseScenario`;
3. `decision` is a C01 `Decision` with a valid in-process approval seal;
4. the decision scope equals the scenario scope;
5. evaluated and expiry times, decision fingerprint and policy evidence
   fingerprint are bound.

The caller must supply complete-cost components and the current monotonic
`policy_epoch` / `source_revision`. N01 revalidates these against its latest
state immediately before every mock/local delivery.

This proposal does not request source approval, real notification authority or
changes to frozen C01/I01 modules.
