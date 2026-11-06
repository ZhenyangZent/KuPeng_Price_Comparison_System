# Windows exact integration preview

## Pinned inputs

- A10 R08 continuation: `CDH_A_R08_001_REVIEW.zip` / `0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd`
- B11: `CDH_B_R07_001_REVIEW.zip` / `6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a`
- B12: `CDH_B_R08_001_REVIEW.zip` / `8e04bcec4e7dd82778858043064dd9676597edade17c496ab16a9042e68bc364`
- C09: `CDH_C_R08_001_REVIEW.zip` / `a8367fed73efce99e93941a6475f386def7dfa25de27b0e2889d4fe00b1ed0d7`
- F07: `CDH_F_R08_001_REVIEW.zip` / `705b8cf34a5315e661de443f27346efa3b97670e81f334f59cb6ab9cd2fff2ee`

## Run

From the project root in PowerShell:

```powershell
python -m tools.ci_web_g08 --run-id G08-local-unique --receipt-ack input/orchestrator_bundles/UNIFIED_CONTINUOUS_20261105_R09/extracted/RECEIPT_ACK.json
```

Expected terminal summary is `INTEGRATION_PASS_SCOPED`, nine passing suites,
zero failed suites, and zero not-run suites. Chrome is launched headless with a
fresh profile below the run directory; both servers bind to ephemeral
`127.0.0.1` ports. Do not substitute an older A10 archive.

No dependency install is performed. The exact A10 lock hash must match the
existing local frontend dependency tree, otherwise A10 tests are reported as
not run rather than downloading packages.
