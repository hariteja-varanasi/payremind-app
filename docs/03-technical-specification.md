# Technical Specification

| | |
|---|---|
| Product | PayRemind |
| Version | 0.1 (app at milestone M4; AWS section describes M5 Terraform, not applied) |
| Date | 26 Nov 2026 |
| Related | [SRS](02-system-requirements.md) · [Data model](04-data-model.md) · [Security](06-security-and-compliance.md) |

## 1. Summary

PayRemind is one Python service. A FastAPI app serves a server-rendered dashboard, a small JSON
API, a public pay page and two webhooks. A command-line tool (`payremind`) handles invites,
migrations and the daily reminder run. Data lives in PostgreSQL (SQLite for local development).
WhatsApp messages go through Meta's Cloud API; PayRemind's own fee goes through Razorpay
Subscriptions. Customers pay merchants directly with UPI, so no money touches PayRemind.

![Components](diagrams/02-components.svg)

## 2. Technology choices

| Area | Choice | Why |
|---|---|---|
| Language | Python 3.12+ (CI and Docker use 3.13) | Owner's learning goal; good libraries for files, HTTP and data |
| Web framework | FastAPI + Uvicorn | Typed request handling, dependency injection for auth and sessions |
| Templates | Jinja2 with autoescape, plain HTML forms, inline CSS | No JavaScript build; strict CSP possible (no scripts at all) |
| ORM and migrations | SQLAlchemy 2.0 (typed `Mapped` models) + Alembic | Portable between SQLite and PostgreSQL; reviewed schema changes |
| Database driver | psycopg 3 | Current PostgreSQL driver |
| Spreadsheet parsing | openpyxl (read-only mode) and the standard `csv` module | Handles Excel and Tally exports |
| QR codes | segno (SVG output, embedded as a data URI) | Pure Python, no image libraries |
| HTTP client | httpx | Timeouts, easy to fake in tests |
| Config | pydantic-settings, `PAYREMIND_*` environment variables | Typed settings, 12-factor style |
| Quality | pytest + coverage (80% gate), ruff, mypy `--strict`, bandit, pip-audit | Run in CI on every push |

## 3. Code layout

```
src/payremind/
  api/app.py          FastAPI factory: JSON API, pay page, webhooks; wires everything
  api/web.py          Dashboard routes: login, upload, promises, mark paid, billing
  api/templates/      Jinja2 pages (dashboard, login, pay, billing, GST invoice, legal)
  auth.py             Phone OTP and web sessions
  services.py         Use cases; every query takes a tenant and filters by tenant_id
  importers/excel.py  .xlsx/.csv parser with header aliases and per-row errors
  core/               Pure logic, no I/O: schedule, ageing, upi, phone
  billing/gst.py      Pure GST maths, GSTIN validation, invoice numbering
  billing/service.py  Plans, subscription status, webhook handling, GST invoice issue
  billing/razorpay.py Razorpay client (and a fake for tests)
  messaging/whatsapp.py  Sender protocol, Cloud API sender, fake sender
  models.py, db.py    SQLAlchemy models and engine
  migrations/         Alembic revisions 0001–0003
  security.py         Token generation, hashing, signature checks
  cli.py              invite, add-user, migrate, run-reminders
tests/                95 tests: unit, API, web, webhooks, billing, migrations, tenant isolation
```

### 3.1 Design rules the code follows

1. **Pure core.** `core/` and `billing/gst.py` take values and return values. They never touch
   the database, the clock or the network, so they are fully unit-tested.
2. **Tenant always explicit.** Every function in `services.py` takes the `Tenant` and adds
   `tenant_id == tenant.id` to every query. Lookups by id use `id AND tenant_id`, so another
   business's id returns "not found" (404), never "forbidden" (which would confirm it exists).
3. **Adapters behind protocols.** `Sender` and `BillingGateway` are protocols with real and fake
   implementations. The app picks the real one only when credentials are configured.
4. **Clock injected.** `create_app` takes `today()` and `now()` functions, so tests control time.
   Business dates use India time (`Asia/Kolkata`); token expiries use Unix seconds.
5. **Idempotency by unique keys.** Reminder log `(tenant_id, invoice_id, offset_days)`, processed
   webhook `event_id`, billing invoice `razorpay_payment_id`. Retries cannot double-act.

## 4. Key flows

### 4.1 Import

1. `POST /imports` (API) or `POST /app/upload` (dashboard) reads at most 5 MB + 1 byte.
2. `parse_invoices` reads the first worksheet or the CSV, scans the first 15 rows for a header,
   maps aliases to fields, and parses each row. Bad rows go into `errors` with a row number.
3. `services.import_rows` upserts customers by `(tenant_id, name)` and invoices by
   `(tenant_id, number)`. A zero balance sets the status to paid. One commit at the end.

### 4.2 Daily reminder run

`payremind run-reminders` (scheduled at 09:30 IST in production) calls `run_all_tenants`:

1. For each tenant where `can_send(tenant, today)` is true (trial still valid, or subscription
   active or past due):
2. Load all opted-out phones once. For each open invoice, load the steps already sent and the
   latest promise date, and build an `InvoiceState`.
3. `core.schedule.due_offset` returns the latest reached step not yet sent, or nothing.
4. Send the `payment_reminder_v1` template in the customer's language with a link to
   `PUBLIC_BASE_URL/p/<pay_token>`.
5. On success, insert a `ReminderLog` row and commit (one commit per message, so a crash halfway
   does not resend what already went). On `SendError`, count a failure and move on; the step is
   tried again next run.

See the [data flow diagram](diagrams/03-data-flow.svg) for the whole path from upload to payment.

### 4.3 Sign-in

1. `POST /login` with a phone number. If it belongs to a user and fewer than 3 codes were issued
   in 15 minutes, store `HMAC(secret_key, phone:code)` with a 5-minute expiry and send the code
   using the `login_code_v1` template. The page looks the same in every case.
2. `POST /login/verify` checks the newest unconsumed, unexpired code, allowing 5 attempts.
3. On success, create a `WebSession` (random token, stored as SHA-256; random CSRF token) and set
   the `pr_session` cookie (HttpOnly, Secure, SameSite=Lax, 7 days).

### 4.4 Billing

1. The merchant saves billing details, picks a plan and is sent to Razorpay's hosted page
   (`short_url`). The subscription id is stored on the tenant.
2. Razorpay calls `POST /webhooks/razorpay`. The app checks the HMAC of the raw body, skips event
   ids already processed, maps the event to a status, and on `subscription.charged` issues a GST
   invoice: the charged amount is treated as GST-inclusive and split 9% + 9% (same state as the
   supplier, Karnataka by default) or 18% IGST. No GST is applied until `SUPPLIER_GSTIN` is set.
3. Invoice numbers are `PR/<FY>/<5-digit sequence>`, restarting each Indian financial year.

> **Note on prices.** The code shows ₹999 and ₹2,499 as prices before GST, while the Razorpay
> plans are expected to charge GST-inclusive amounts. The Razorpay plan amounts must therefore be
> set to the price plus GST once registered (for example ₹1,178.82 for Starter at 18%).
> **⚖ Verify** pricing display and GST treatment with a CA.

## 5. Configuration

All settings are environment variables with the `PAYREMIND_` prefix (see `.env.example`).

| Variable | Purpose | Secret? |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy URL (SQLite locally, PostgreSQL in production) | Yes (contains password) |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Meta Cloud API sender; empty means fake sender | Token yes |
| `WHATSAPP_APP_SECRET` | Verifies Meta webhook signatures | Yes |
| `WHATSAPP_VERIFY_TOKEN` | Webhook subscription handshake | Yes |
| `PUBLIC_BASE_URL` | Used to build pay page links | No |
| `SECRET_KEY` | Keys OTP hashes. **Must be set in production**; if empty a random key is used and pending codes break on restart | Yes |
| `COOKIE_SECURE` | `false` only for local http | No |
| `SESSION_DAYS` | Session lifetime (default 7) | No |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Razorpay API | Secret yes |
| `RAZORPAY_WEBHOOK_SECRET` | Verifies Razorpay webhooks | Yes |
| `RAZORPAY_PLAN_STARTER`, `RAZORPAY_PLAN_GROWTH` | Plan ids from the Razorpay dashboard | No |
| `SUPPLIER_NAME`, `SUPPLIER_GSTIN`, `SUPPLIER_STATE_CODE`, `SUPPLIER_ADDRESS` | PayRemind's details on GST invoices | No |
| `MAX_UPLOAD_BYTES`, `MAX_IMPORT_ROWS` | Import limits (5 MB, 5,000 rows) | No |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | On AWS, used instead of `DATABASE_URL` (TLS required) | Password yes |

## 6. Build, test and release

- `make install`, `make check` (ruff, format check, mypy strict, bandit, pip-audit), `make test`.
- CI (GitHub Actions) runs the same on every push and pull request, with read-only permissions, plus an `infra` job: `terraform fmt`, `validate`, `test` and Checkov.
- Tests run on SQLite by default; set `PAYREMIND_TEST_DATABASE_URL` to run them on PostgreSQL.
- `Dockerfile`: `python:3.13-slim`, installs the package, runs as non-root user `app` (uid 10001),
  starts Uvicorn on port 8000 with proxy headers trusted only from the VPC range. Run `payremind migrate` before starting a new version.
- Branching: feature branches and pull requests into `main`; one PR per milestone so far.

## 7. AWS deployment (M5: Terraform written, not applied)

> The Terraform in `infra/terraform` describes every resource below, and CI checks it offline
> (`terraform validate`, `terraform test` with a mocked plan, Checkov). **Nothing has been
> applied.** Running `terraform apply` needs Hari's go-ahead. The full runbook and cost table are
> in [infra/README.md](../infra/README.md).

![AWS deployment](diagrams/04-aws-planned.svg)

| Concern | Design in the Terraform |
|---|---|
| Region | ap-south-1 (Mumbai), one account |
| Edge | CloudFront with HSTS and AWS WAF: IP reputation list, OWASP common rules, known bad inputs, India-only except `/webhooks/`, 20 login requests per IP per 5 minutes, global rate limit |
| Origin protection | The load balancer accepts only CloudFront's IP ranges and returns 403 without a secret `X-Origin-Verify` header |
| Compute | ECS Fargate, ARM (Graviton), 0.25 vCPU and 0.5 GB, read-only root filesystem; Uvicorn trusts forwarded headers only from inside the VPC |
| Network | VPC 10.20.0.0/16. App tasks in public subnets with a public IP for outbound calls only; their security group accepts traffic from the load balancer only. Database in private subnets with no internet route. No NAT gateway (saves roughly $35 a month) |
| Daily job | EventBridge Scheduler, `cron(30 9 * * ? *)` in Asia/Kolkata, starts a one-off Fargate task running `payremind run-reminders`. Off until templates are approved (`reminders_enabled`) |
| Database | RDS PostgreSQL 16, `db.t4g.micro`, single-AZ, encrypted, TLS forced (`sslmode=require`), 7-day backups with point-in-time restore, deletion protection |
| Secrets | SSM Parameter Store SecureString under `/payremind/<env>/`. Terraform generates `secret_key`, the WhatsApp verify token and the origin secret; real API keys are entered by hand with the AWS CLI. The database password is managed and rotated by RDS |
| Configuration | The app builds its database URL from `PAYREMIND_DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`; parameters still holding the placeholder `unset` are treated as empty |
| Logging and detection | App logs and VPC flow logs (rejects) in CloudWatch for 365 days; load balancer access logs and CloudTrail in S3 for 365 days; GuardDuty findings of medium and above, and budget alerts, by email |
| Cost | About $70–82 a month for low beta traffic; budget alert at 50% and 100% of $100 |
| Deploys | Push an ARM64 image to ECR, then `terraform apply -var image_tag=<sha>`; ECS rolls back if health checks fail. Migrations run as a one-off task |

### 7.1 Decision record: how the app reaches both the database and the internet

**Problem.** The app and the daily job need the private database and also Meta's and Razorpay's
public APIs. The usual answer, a NAT gateway, costs roughly $35–40 a month before data charges.

**Options considered.** Managed NAT gateway; a NAT instance; IPv6 egress-only gateway;
splitting the job with a queue; Aurora with the Data API; a public database endpoint (rejected);
running containers with a public IP in public subnets.

**Decision (M5 Terraform).** Run Fargate tasks in public subnets with a public IP, used only for
outbound calls. The security group allows inbound traffic from the load balancer only, so the
public IP does not expose the app. The database stays in private subnets with no route to the
internet. The original plan's Lambda + API Gateway design was replaced by Fargate + a load
balancer, which avoids the Lambda-in-VPC egress problem and runs the app unchanged.

**Trade-offs.** Each public IPv4 address costs about $3.60 a month; the load balancer and its IPs
are the biggest cost line (~$30). A misconfigured security group would expose the task directly,
so the rule is tested in `terraform test` and checked by Checkov. Other accepted beta trade-offs
(single-AZ database, AWS-managed keys, sampled WAF logs) are listed with reasons in
`infra/terraform/.checkov.yaml`.

### 7.2 Remaining infrastructure items

- Apply the Terraform (after Hari approves), set the real secrets, push the first image, migrate,
  invite the first business, then switch the daily job on.
- Add structured JSON logging to the app (request id, tenant id, route, status, no personal data)
  so the 365-day CloudWatch logs are useful in an incident. The app logs nothing today.
- Test a restore from an RDS snapshot; run OWASP ZAP against the beta URL.
- Reconsider Multi-AZ and customer-managed keys before public launch.

## 8. Known technical gaps (found while writing)

| # | Gap | Suggested fix |
|---|---|---|
| G-1 | No application logging or audit trail (who marked what paid, who logged in) | Structured logging plus an `audit_events` table |
| G-2 | API bearer tokens never expire and cannot be rotated | `payremind rotate-token`; optional expiry |
| G-3 | Plan limits (customers, Hindi on Growth) are displayed but not enforced | Check in `import_rows` and when sending |
| G-4 | GST invoice numbers use "count + 1"; two charges at the same moment could collide (the unique key rejects one, and Razorpay retries) | A database sequence or a locked counter row per FY |
| G-5 | Expired OTP challenges and sessions are never deleted | Clean-up step in the daily job |
| G-6 | openpyxl parses untrusted XML; it is safer with `defusedxml` installed, and a 5 MB `.xlsx` can expand a lot when unzipped | Add `defusedxml`; cap uncompressed size |
| G-7 | No opt-in (START) after STOP | Handle START in the webhook |
| G-8 | No partial payments; mark-paid sets balance to zero | `POST /invoices/{id}/payments` with an amount |
| G-9 | No data export or delete for a merchant, although the DPA promises help | Operator CLI first, then a dashboard button |
| G-10 | `SECRET_KEY` silently falls back to a random value (Terraform now supplies one on AWS, but nothing stops a deploy without it) | Fail fast when unset outside development |
