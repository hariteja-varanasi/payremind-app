# PayRemind

WhatsApp-first payment reminders for Indian MSMEs. Upload an Excel/CSV export of
outstanding invoices, see what's overdue, and send scheduled WhatsApp reminders with a
UPI link that pays the merchant's own UPI ID. We never hold money.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
make install
payremind invite --name "Demo Traders" --upi demo@okaxis --payee "Demo Traders"   # prints a token once
make run
curl -H "Authorization: Bearer <token>" -F file=@outstanding.csv localhost:8000/imports
curl -H "Authorization: Bearer <token>" "localhost:8000/invoices?overdue=true"
curl -H "Authorization: Bearer <token>" -X POST localhost:8000/reminders/run
```

Without WhatsApp credentials, reminders go to an in-memory fake sender.

## Checks

`make check` (ruff, mypy strict, bandit, pip-audit) and `make test` (pytest, coverage gate 80%).
See [PLAN.md](PLAN.md) for scope, milestones and launch gates.
