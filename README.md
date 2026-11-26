# PayRemind

WhatsApp-first payment reminders for Indian MSMEs. Upload an Excel/CSV export of
outstanding invoices, see what's overdue, and send scheduled WhatsApp reminders with a
UPI link that pays the merchant's own UPI ID. We never hold money.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
make install
payremind migrate                                                               # creates/updates tables
payremind invite --name "Demo Traders" --upi demo@okaxis --payee "Demo Traders" \
  --owner-phone 9845012345                                                      # prints an API token once
PAYREMIND_COOKIE_SECURE=false make run                                          # then open localhost:8000

curl -H "Authorization: Bearer <token>" -F file=@outstanding.csv localhost:8000/imports
curl -H "Authorization: Bearer <token>" "localhost:8000/invoices?overdue=true"
curl -H "Authorization: Bearer <token>" -X POST localhost:8000/reminders/run
```

Sign in at `/login` with the owner's phone. Without WhatsApp credentials, login codes and
reminders go to an in-memory fake sender, so for local testing read the code from a test or
configure a WhatsApp test number. The dashboard covers upload, open and overdue invoices,
ageing totals, promise-to-pay dates, mark paid and "send due reminders now".

`payremind run-reminders` is the daily job (9:30 IST in production): it sends due reminders
for every business and is safe to re-run. Customers with `language` = `hi` in the upload get
the Hindi template. Template texts for Meta are in [docs/whatsapp-templates.md](docs/whatsapp-templates.md).

Each reminder links to `PAYREMIND_PUBLIC_BASE_URL/p/<token>`, a pay page with a UPI button
and QR code that pays the merchant's own UPI ID. Customers who reply STOP (or "band karo")
are opted out for every merchant; `POST /webhooks/whatsapp` checks Meta's signature first.

Tests run on SQLite by default. Set `PAYREMIND_TEST_DATABASE_URL` to a Postgres URL to run
them against Postgres, as CI does.

## Billing (our fee)

`/app/billing` lets a business enter GST billing details, pick a plan (Starter ₹999 or Growth
₹2,499 a month + GST) and pay on Razorpay's hosted page. `POST /webhooks/razorpay` (signature
checked, each event processed once) keeps the subscription status in sync and issues a GST
invoice for every charge: CGST + SGST for Karnataka buyers, IGST otherwise, numbered
`PR/<FY>/<n>`. New businesses get a 30-day trial (`--trial-days 0` = free beta). Reminders pause
when a trial ends or a subscription is halted, paused or cancelled.

Draft privacy policy and terms are served at `/privacy` and `/terms`; the merchant DPA is in
[docs/legal/dpa.md](docs/legal/dpa.md). **All three are drafts that need a lawyer's review.**

## Checks

`make check` (ruff, mypy strict, bandit, pip-audit) and `make test` (pytest, coverage gate 80%).
See [PLAN.md](PLAN.md) for scope, milestones and launch gates.
