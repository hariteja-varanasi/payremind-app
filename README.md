# PayRemind

WhatsApp-first payment reminders for Indian MSMEs. Upload an Excel/CSV export of
outstanding invoices, see what's overdue, and send scheduled WhatsApp reminders with a
UPI link that pays the merchant's own UPI ID. We never hold money.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
make install
payremind migrate                                                               # creates/updates tables
payremind invite --name "Demo Traders" --upi demo@okaxis --payee "Demo Traders"   # prints a token once
make run
curl -H "Authorization: Bearer <token>" -F file=@outstanding.csv localhost:8000/imports
curl -H "Authorization: Bearer <token>" "localhost:8000/invoices?overdue=true"
curl -H "Authorization: Bearer <token>" -X POST localhost:8000/reminders/run
```

Without WhatsApp credentials, reminders go to an in-memory fake sender.

Each reminder links to `PAYREMIND_PUBLIC_BASE_URL/p/<token>`, a pay page with a UPI button
and QR code that pays the merchant's own UPI ID. Customers who reply STOP (or "band karo")
are opted out for every merchant; `POST /webhooks/whatsapp` checks Meta's signature first.

Tests run on SQLite by default. Set `PAYREMIND_TEST_DATABASE_URL` to a Postgres URL to run
them against Postgres, as CI does.

## Checks

`make check` (ruff, mypy strict, bandit, pip-audit) and `make test` (pytest, coverage gate 80%).
See [PLAN.md](PLAN.md) for scope, milestones and launch gates.
