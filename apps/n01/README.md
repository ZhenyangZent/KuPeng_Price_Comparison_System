# N01 offline alert queue

N01 is an offline-only, synthetic notification preparation lane. It accepts
approved in-process C01/I01 decisions, persists a SQLite outbox, revalidates the
latest state before dispatch, and can deliver only to `MockSink` or an explicitly
rooted local synthetic JSONL log.

Windows Toast and Telegram are interface proposals only. This package contains
no token loader, HTTP client, toast activation, Registry access, browser profile
access, Coupang collector, cart, coupon-claim, checkout, order, or payment code.

Run tests from the project root:

```powershell
$env:PYTHONPATH = "src;apps/n01"
$env:TEMP = (Resolve-Path "experiments/N01/test_tmp")
$env:TMP = $env:TEMP
python -m unittest discover -s tests/n01 -p "test_*.py" -v
```
