# N01 future permissions proposal

Current state: `INTERFACE_ONLY_DISABLED`

## Windows Toast

Future separate authority should name the Windows implementation, approved app
identity, payload display rules, user opt-in/disable control, and Windows test
matrix. It must not require Registry writes unless a later authority explicitly
adds and audits them. This N01 release does not instantiate a Toast API.

## Telegram

Future separate authority should define the secret provider, approved chat
alias mapping, rate limits, retry/ambiguous-delivery handling, revocation and
credential rotation. Tokens must never be stored in fixtures, SQLite payloads,
logs or review ZIPs. This release neither reads tokens nor imports a network
client.

## Required gate before enablement

- Explicit new authority and security review.
- Windows/network E2E evidence appropriate to the selected channel.
- User-visible dry-run and enable/disable controls.
- Retention and redaction review.
- Confirmation that real source permission is independent of notification
  channel permission; `SOURCE_BLOCKED` must not be upgraded by this work.
