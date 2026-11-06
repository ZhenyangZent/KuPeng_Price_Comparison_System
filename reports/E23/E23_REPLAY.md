# E23 audit replay from the REVIEW ZIP

The handoff ZIP includes `scripts/orchestrator_handoff/e23_release_audit.py`, `e23_risk_triage.py`, `flat_queue.py`, `handoff_batch.py`, and both `tests/handoff/test_e23_*.py` files. `flat_queue.py` imports `handoff_batch.py`; both are required. The tests use only the Python standard library and create synthetic fixtures inside the extracted project's `experiments/E23` directory.

From a writable, isolated extraction inside the authorized project root:

```powershell
python -m unittest discover -s tests/handoff -p 'test_e23_*.py' -v
```

The eight targeted tests cover strict manifest acceptance, credential-pattern rejection, unopened private SQLite and nested ZIP members, immutable 140-file baseline, incremental snapshot identity, metadata-only private-member exclusion and image-review gating. The `BASELINE_140.json`, seven old `batch_??.json` checkpoints and new snapshot/checkpoint are included for read-only reconciliation. Tests do not access the real release originals or any production database.
