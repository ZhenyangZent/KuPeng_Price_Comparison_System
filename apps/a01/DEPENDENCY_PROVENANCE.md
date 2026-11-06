# A01 Dependency Provenance

- Runtime: CPython embeddable `3.12.7` Windows x64.
- Python archive SHA-256: `0d57bb6cb078b74d23dbfe91f77d6780d45bed328911609f1f7ee2ba1606bf44`.
- Bootstrap `get-pip.py` SHA-256: `f4448a01e3ab2914c65f4ca59d4cacba6b2dbde19a483fbac46587f8bbaff424`.
- GUI: PySide6 `6.8.1`; each Windows wheel is hash-bound in `requirements.lock`.
- Development downloads and `.venv` are excluded from the review ZIP.

Rebuild the project-local environment only under `apps/a01/.venv`; do not install globally:

```powershell
apps\a01\.venv\python.exe -m pip install --require-hashes -r apps\a01\requirements.lock
```
