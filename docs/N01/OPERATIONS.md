# N01 offline operations

Run only in an isolated synthetic workspace such as `experiments/N01/`.

```powershell
New-Item -ItemType Directory -Force experiments/N01/test_tmp | Out-Null
$env:PYTHONPATH = ((Resolve-Path 'src').Path + ';' + (Resolve-Path 'apps/n01').Path + ';' + (Resolve-Path '.').Path)
$env:TEMP = (Resolve-Path 'experiments/N01/test_tmp').Path
$env:TMP = $env:TEMP
python -m unittest discover -s tests/n01 -p 'test_*.py' -v
```

`MockSink` is the default. `LocalSyntheticJsonlSink` requires both the target
path and an enclosing synthetic root, and rejects escape paths. Windows Toast
and Telegram interface classes always raise `RealDeliveryDisabled`.

Operational statistics report queue states, attempts, retries and filters, plus
the invariant `real_delivery_count=0` and
`external_exactly_once_claimed=false`.
