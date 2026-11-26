# Launch Checklist

Two stages: the **invite-only beta** (10–20 businesses, M5) and **public launch**. Tick items in
pull requests as they are done. Items marked **⚖** need a professional.

Status at 26 Nov 2026: M1–M4 merged; nothing deployed.

## Stage 0: accounts and approvals (Hari, no cost)

- [ ] Meta Business account verified; WhatsApp Business number added.
- [ ] `payment_reminder_v1` submitted and approved in English and Hindi (native speaker checked
      the Hindi). See [whatsapp-templates.md](whatsapp-templates.md).
- [ ] `login_code_v1` authentication template approved.
- [ ] Webhook callback set to `https://<domain>/webhooks/whatsapp`, subscribed to `messages`.
- [ ] Razorpay account KYC complete; Starter and Growth monthly plans created in test mode, then
      live mode, at GST-inclusive amounts.
- [ ] Razorpay webhook created with a secret; events: subscription.*.
- [ ] Domain name chosen and DNS ready.

## Stage 1: before the invite-only beta (M5)

### Infrastructure (needs Hari's go-ahead to create anything in AWS)

- [ ] Decide database connectivity option (tech spec §7.1) and record the decision.
- [ ] Terraform for: CloudFront + WAF, API Gateway, two Lambdas, EventBridge Scheduler,
      RDS PostgreSQL (encrypted, backups on), Secrets Manager, ECR, log groups (180 days).
- [ ] AWS account basics: root MFA, no root access keys, IAM roles with least privilege,
      CloudTrail on, GuardDuty on.
- [ ] AWS Budgets alarms at $50 and $100.
- [ ] TLS certificate (ACM) on CloudFront; `PAYREMIND_COOKIE_SECURE=true`.
- [ ] `PAYREMIND_SECRET_KEY` and all API secrets in Secrets Manager, never in Terraform state
      in plain text.
- [ ] `payremind migrate` runs as a deploy step before the new version takes traffic.
- [ ] Daily job fires at 09:30 IST; first run checked by hand.

### Application

- [ ] Structured logging with no personal data in logs (G-1).
- [ ] `defusedxml` added; `.xlsx` uncompressed-size cap (G-6).
- [ ] App refuses to start in production without `SECRET_KEY` (G-10).
- [ ] Plan limits enforced or removed from the billing page (G-3).
- [ ] Clean-up of expired codes and sessions (G-5).

### Quality and security gates (from PLAN.md)

- [x] Coverage ≥ 80% on core logic (about 99% overall today).
- [x] 100% of tenant-isolation tests pass.
- [x] ruff, mypy `--strict`, bandit, pip-audit clean in CI.
- [ ] CodeQL or Semgrep: no open high or critical findings.
- [ ] OWASP ZAP baseline scan: no open high or critical findings.
- [ ] Backup restore tested end to end (write down how long it took).
- [ ] Load test of the reminder run (for example 20 businesses × 5,000 invoices with the fake
      sender).
- [ ] Incident runbook written, with the CERT-In 6-hour path. **⚖**

### Legal and tax

- [ ] Lawyer review of `/privacy`, `/terms` and `docs/legal/dpa.md`; bracketed items filled. **⚖**
- [ ] Confirmation that direct-to-merchant UPI needs no RBI payment aggregator licence. **⚖**
- [ ] Confirmation of the DPDP processor role and merchant obligations. **⚖**
- [ ] CA review: GST registration timing, SAC 998314, invoice format, record retention. **⚖**
- [ ] Each beta merchant accepts the terms and DPA.

### Beta operations

- [ ] Invite first businesses with `payremind invite` (decide trial days or free beta).
- [ ] One-page "how to export your outstanding list" guide for Tally, Busy and Excel.
- [ ] Support channel (a WhatsApp number or email) and expected response time.
- [ ] Weekly check: sends, failures, opt-out rate, cost.

## Stage 2: before public launch

- [ ] Beta feedback reviewed; success measures in the BRD compared with results.
- [ ] Public sign-up flow designed with abuse controls (it does not exist today).
- [ ] API token rotation (G-2), audit log (G-1), data export and delete (G-9).
- [ ] Multi-AZ database or a documented recovery time the business accepts.
- [ ] Pen test or external security review.
- [ ] Privacy policy and terms published as final (not draft). **⚖**
- [ ] GST registration in place if required, and live GST invoices checked by a CA. **⚖**
- [ ] Monitoring and alerting on the daily job and error rates.
