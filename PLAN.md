# PayRemind repo plan

Goal: invite-only beta with 10–20 MSMEs in ~6 weeks, at 30–60 min/day of build time.
Public launch only after the gates at the bottom pass.

## MVP scope (in)
1. Import outstanding invoices from .xlsx / .csv (Excel, Tally, Busy exports). **Done (scaffold).**
2. Overdue list and ageing buckets (not due, 1–30, 31–60, 61–90, 90+). **Done (API).**
3. Reminder rules: 3 days before, due day, 7 and 15 days late; one per step, idempotent,
   skipped when paid, opted out, no phone, or a promise to pay is active. **Done (logic + fake sender).**
4. UPI link to the merchant's own UPI ID, via an https pay page with QR. **Done.**
5. Promise-to-pay tracking and mark-paid. **Done (API).**
6. WhatsApp Cloud API sender with one utility template. **Code done; needs Meta account + template approval.**
7. Razorpay subscriptions for our own fee, with GST invoices. **Done.**

Out of scope for beta: Tally XML/ODBC sync, regional-language templates beyond Hindi,
payment reconciliation from bank feeds, mobile app, CA multi-client view.

## Layout
```
src/payremind/
  core/        pure logic: ageing, schedule, upi, phone (no I/O, fully unit-tested)
  importers/   excel/csv parser with header aliasing and per-row errors
  messaging/   Sender protocol, FakeSender, WhatsApp CloudApiSender
  services.py  use cases; every query is tenant-scoped
  api/app.py   FastAPI routes, bearer-token auth per tenant
  cli.py       `payremind invite` creates beta tenants (no public sign-up)
tests/         unit, API, and tenant-isolation gate tests
```

## Milestones
- **M1 (this week):** scaffold, core logic, tests, CI. ✅
- **M2:** Alembic migrations, Postgres, https pay page per invoice (`/p/<token>` with UPI
  button + QR) because WhatsApp doesn't reliably make `upi://` links tappable; STOP/opt-out
  webhook. ✅ (Hindi template moved to M3, it needs Meta approval first.)
- **M3:** Hindi template, minimal web UI (Jinja forms, no JS build), phone OTP sign-in over
  WhatsApp, daily scheduler command. ✅
- **M4:** Razorpay subscriptions + GST invoice for our fee; privacy policy, terms, DPA (drafts). ✅
- **M5:** AWS beta deploy (below), invite first CAs and their clients.

## AWS beta (ap-south-1), target ~$50–150/month. Not created yet; needs Hari's go-ahead.
- Lambda (container image, via Mangum) behind API Gateway HTTP API; CloudFront + WAF in front.
- RDS Postgres db.t4g.micro, single-AZ for beta, encrypted with KMS, automated backups.
- EventBridge Scheduler (timezone Asia/Kolkata, 09:30) runs `payremind run-reminders`.
- WAF rate rule on `/login` and `/login/verify` per IP, on top of the app's per-phone limits.
- Secrets Manager for WhatsApp/Razorpay keys; CloudTrail, GuardDuty, CloudWatch logs kept 180 days (CERT-In).
- No NAT gateway; Lambda outside VPC for outbound calls, RDS reached via RDS Proxy or
  a VPC Lambda with VPC endpoints (decide in M5 with the pricing calculator).
- Terraform, budget alarm at $50 and $100.

## Launch gates (before any public exposure)
- Coverage ≥80% on core logic (currently 99% overall); 100% of tenant-isolation tests pass.
- ruff, mypy --strict, bandit, pip-audit clean in CI; CodeQL/Semgrep and OWASP ZAP with no open high/critical.
- Backup restore tested; 6-hour incident runbook (CERT-In); load test of the reminder run.
- Privacy policy, terms, DPA live; Razorpay + GST invoicing working.
- Lawyer review of `/privacy`, `/terms` and `docs/legal/dpa.md` (fill in the bracketed items).
- CA review: GST registration timing, SAC code 998314, invoice format and record retention.
- Verify with a professional: payments flow straight to merchant UPI (no RBI PA licence needed),
  GST registration, DPDP processor role.

## Needs Hari (no cost)
- Meta Business account + WhatsApp Business number; submit the templates in
  `docs/whatsapp-templates.md` (have a native speaker check the Hindi).
- Razorpay account (KYC takes days); create Starter and Growth monthly plans in test mode first.
