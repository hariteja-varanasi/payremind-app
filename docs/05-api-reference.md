# API and Routes

Every HTTP route and command the app exposes at milestone M4. Source: `api/app.py`, `api/web.py`
and `cli.py`. FastAPI's automatic `/docs` page is switched off on purpose, so this page is the
reference.

## 1. Summary

| Method | Path | Who calls it | Auth | Purpose |
|---|---|---|---|---|
| GET | `/health` | Monitoring | None | Liveness check |
| POST | `/imports` | API client | Bearer | Upload `.xlsx` / `.csv` |
| GET | `/invoices` | API client | Bearer | List open invoices |
| GET | `/ageing` | API client | Bearer | Totals per ageing bucket |
| POST | `/invoices/{id}/promises` | API client | Bearer | Record a promise to pay |
| POST | `/invoices/{id}/paid` | API client | Bearer | Mark an invoice paid |
| POST | `/reminders/run` | API client | Bearer | Send due reminders now (this business only) |
| GET | `/p/{token}` | Customer | Pay token | Pay page with UPI button and QR |
| GET | `/webhooks/whatsapp` | Meta | Verify token | Webhook subscription handshake |
| POST | `/webhooks/whatsapp` | Meta | HMAC signature | STOP replies (opt-out) |
| POST | `/webhooks/razorpay` | Razorpay | HMAC signature | Subscription and payment events |
| GET | `/` | Browser | None | Redirects to `/app` |
| GET | `/privacy`, `/terms` | Anyone | None | Draft legal pages |
| GET | `/login` | Browser | None | Phone number form |
| POST | `/login` | Browser | None | Send a login code on WhatsApp |
| POST | `/login/verify` | Browser | None | Check the code, set the session cookie |
| POST | `/logout` | Browser | Session + CSRF | End the session |
| GET | `/app` | Browser | Session | Dashboard |
| POST | `/app/upload` | Browser | Session + CSRF | Upload a file |
| POST | `/app/invoices/{id}/paid` | Browser | Session + CSRF | Mark paid |
| POST | `/app/invoices/{id}/promise` | Browser | Session + CSRF | Record a promise date |
| POST | `/app/reminders/run` | Browser | Session + CSRF | Send due reminders now |
| GET | `/app/billing` | Browser | Session | Plans, billing details, our invoices |
| POST | `/app/billing/details` | Browser | Session + CSRF | Save legal name, GSTIN, state, address |
| POST | `/app/billing/subscribe` | Browser | Session + CSRF | Start a Razorpay subscription |
| POST | `/app/billing/cancel` | Browser | Session + CSRF | Cancel at end of cycle |
| GET | `/app/billing/invoices/{id}` | Browser | Session | View one GST invoice |

## 2. JSON API (bearer token)

Send `Authorization: Bearer <token>`. The token is printed once by `payremind invite`. A missing
or wrong token returns `401`. An invoice id that belongs to another business returns `404`.

### `POST /imports`

Multipart form with one field, `file`.

```bash
curl -H "Authorization: Bearer $TOKEN" -F file=@outstanding.csv https://<host>/imports
```

```json
{ "created": 42, "updated": 3, "errors": ["row 7: unrecognised date '31/31/2026'"] }
```

| Status | When |
|---|---|
| 200 | File read; some rows may still be in `errors` |
| 413 | Larger than 5 MB |
| 422 | Not `.xlsx`/`.csv`, no header row found, more than 5,000 rows, or corrupt file |

### `GET /invoices?overdue=true`

Open invoices, most overdue first. `overdue=true` keeps only those past their due date.

```json
[{ "id": 12, "number": "INV-104", "customer": "Sharma Traders",
   "due_date": "2026-11-01", "balance": "12500.00", "days_overdue": 25 }]
```

### `GET /ageing`

```json
{ "not_due": "8000.00", "1_30": "12500.00", "31_60": "0", "61_90": "0", "90_plus": "4300.00" }
```

### `POST /invoices/{id}/promises`

```json
{ "promised_date": "2026-12-10", "amount": "12500.00", "note": "Will pay after Diwali stock clears" }
```

Returns `201` with `{ "id": 5 }`. `amount` must be above 0 with at most 2 decimals; `note` at
most 500 characters. Reminders pause until the promised date (inclusive).

### `POST /invoices/{id}/paid`

No body. Sets the balance to 0 and the status to paid. Returns the invoice as in `/invoices`.

### `POST /reminders/run`

No body. Sends due reminders for this business only, using the same rules as the daily job.
Returns `{ "sent": 3, "failed": 0 }`, or `402` if the trial has ended or the subscription is not
active.

## 3. Public pay page

### `GET /p/{token}`

HTML page for one invoice: payee, UPI ID, invoice number, due date, amount, a "Pay with UPI"
button (`upi://pay?...`) and a QR code of the same link. Shows "paid" without a button when the
balance is 0. Tokens shorter than 16 or longer than 64 characters, or unknown tokens, return a
plain `404`. Response headers include a CSP that allows no scripts, `Referrer-Policy: no-referrer`,
`X-Robots-Tag: noindex, nofollow` and `Cache-Control: no-store`.

Example UPI link built for the page:

```
upi://pay?pa=demo@okaxis&pn=Demo%20Traders&am=12500.00&cu=INR&tn=Invoice%20INV-104
```

## 4. Webhooks

Both handlers read at most 256 KB and check the signature **before** parsing the JSON.

### `GET /webhooks/whatsapp`

Meta's subscription check. Returns `hub.challenge` as plain text only when `hub.mode=subscribe`,
the challenge is numeric and `hub.verify_token` matches `PAYREMIND_WHATSAPP_VERIFY_TOKEN`.
Otherwise `403`.

### `POST /webhooks/whatsapp`

Requires `X-Hub-Signature-256: sha256=<HMAC of raw body with WHATSAPP_APP_SECRET>`. Looks for
text messages or quick-reply buttons saying STOP, UNSUBSCRIBE, STOP REMINDERS, BAND KARO or
बंद करो and opts those numbers out. Returns `{ "opted_out": 1 }`. Bad signature `401`; bad JSON
`400`; too large `413`.

### `POST /webhooks/razorpay`

Requires `X-Razorpay-Signature` (HMAC-SHA256 of raw body with `RAZORPAY_WEBHOOK_SECRET`) and
uses `X-Razorpay-Event-Id` to process each event once. Handles `subscription.authenticated`,
`activated`, `charged`, `resumed`, `pending`, `halted`, `paused`, `cancelled` and `completed`.
On `subscription.charged` it issues a GST invoice. Returns `{ "result": "status active, invoice
PR/2026-27/00001" }` or `duplicate` / `ignored`.

## 5. Dashboard routes

Server-rendered HTML forms. All POSTs under `/app` and `/logout` need the hidden `csrf` field;
a wrong value returns `403`. Without a valid session cookie, `/app` routes redirect to `/login`
(`303`). Result messages come from a fixed list selected by `?m=<key>`, so user input is never
reflected into the page.

| Route | Form fields | Result |
|---|---|---|
| `POST /login` | `phone` | Always shows the code page for a valid number (whether or not it is registered); `422` for a malformed number |
| `POST /login/verify` | `phone`, `code` | `303` to `/app` with cookie `pr_session`, or `401` with a retry message |
| `POST /app/upload` | `file`, `csrf` | Dashboard with counts and up to 50 row errors |
| `POST /app/invoices/{id}/promise` | `promised_date`, `csrf` | Promise for the full balance; date must be today or later |
| `POST /app/billing/details` | `legal_name`, `gstin` (optional), `state_code`, `billing_address`, `csrf` | GSTIN checksum validated |
| `POST /app/billing/subscribe` | `plan` (`starter` or `growth`), `csrf` | Page with a link to Razorpay's hosted checkout |

## 6. Command line (`payremind`)

| Command | What it does |
|---|---|
| `payremind migrate` | Apply database migrations up to the latest |
| `payremind invite --name N --upi ID --payee P --owner-phone 98xxxxxxxx [--trial-days 30]` | Create a business and its first user; print the API token once. `--trial-days 0` = free beta |
| `payremind add-user --tenant 1 --phone 98xxxxxxxx` | Let another phone sign in to a business |
| `payremind run-reminders` | The daily job for every business in good standing; prints businesses, sent and failed. Says "dry run" when WhatsApp is not configured |

Exit code `2` with a message on invalid input.
