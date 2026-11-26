# Business Requirements Document (BRD)

| | |
|---|---|
| Product | PayRemind: WhatsApp payment reminders for Indian MSMEs |
| Version | 0.1 (describes code at milestone M4) |
| Date | 26 Nov 2026 |
| Owner | Hari |
| Status | Draft for review |

> **⚖ Verify.** Anything below about GST, RBI rules, data protection law or WhatsApp policy is a
> planning assumption, not advice. Each is listed again in the
> [launch checklist](07-launch-checklist.md) for a professional to confirm.

## 1. Purpose of this document

This document explains the business problem PayRemind solves, who it is for, what is in and out
of scope for the invite-only beta, and how success will be judged. It deliberately says
**what** and **why**. The [SRS](02-system-requirements.md) says what the system must do in
testable detail, and the [technical specification](03-technical-specification.md) says how.

## 2. Background and problem

Small Indian businesses (traders, distributors, manufacturers, service firms) commonly sell on
credit. Collecting those payments is manual: someone scrolls through the outstanding report in
Tally or Excel and phones or messages each customer. It is awkward, easy to forget, and late
payments squeeze working capital.

Three facts make a simple tool useful:

1. **WhatsApp is where business conversations already happen** in India, so a reminder there is
   more likely to be read than an email.
2. **UPI makes paying instant.** A reminder that opens a UPI payment with the amount filled in
   removes most of the effort of paying.
3. **The data already exists.** Accounting software can export an "outstanding invoices" list,
   so the merchant does not need to type anything in.

## 3. Business objectives

| # | Objective | How we will know |
|---|---|---|
| BO-1 | Help merchants get paid sooner with less effort | Beta merchants report less time spent chasing payments; share of reminded invoices paid within 15 days of due date |
| BO-2 | Validate that MSMEs will pay a monthly fee for this | At least a few beta merchants convert from trial to a paid plan |
| BO-3 | Stay low-risk and low-cost to run | Hosting at or under about $50–150 a month for the beta; no handling of customer money |
| BO-4 | Serve as a real, secure, well-tested portfolio project | Launch gates in PLAN.md pass (tests, scans, tenant isolation, backups, incident runbook) |

Making money is secondary to BO-4 for the owner. The product should still be run as if it were a
real business, because that is what makes it a credible learning project.

## 4. Stakeholders and users

| Stakeholder | Role | What they need |
|---|---|---|
| Merchant (owner or accountant) | Main user | Upload a list, see who owes what, have reminders go out without effort, mark invoices paid |
| Merchant's customer (buyer) | Receives reminders | A clear, polite message and a one-tap way to pay; a way to stop messages |
| Chartered accountant (CA) | Likely channel for the beta | Something simple to recommend to clients |
| Operator (Hari) | Runs the service | Invite businesses, run migrations, watch the daily job, keep costs low |
| Meta (WhatsApp) | Messaging platform | Approved templates, opt-out respected, quality rules followed |
| Razorpay | Collects PayRemind's fee | Correct use of subscriptions and webhooks |
| Professionals (lawyer, CA) | Review | Clear list of legal and tax assumptions to check |

## 5. Scope

### 5.1 In scope for the invite-only beta

| # | Capability | Status at M4 |
|---|---|---|
| S-1 | Import outstanding invoices from `.xlsx` or `.csv` exports (Excel, Tally, Busy, Vyapar), with clear per-row errors | Built |
| S-2 | Overdue list and ageing totals (not due, 1–30, 31–60, 61–90, 90+ days) | Built |
| S-3 | Automatic reminders 3 days before, on the due day, 7 days late and 15 days late, at most one per step | Built |
| S-4 | A pay page per invoice with a UPI button and QR code that pays the merchant's own UPI ID | Built |
| S-5 | Promise-to-pay dates that pause reminders, and mark-as-paid | Built |
| S-6 | WhatsApp delivery through Meta's Cloud API, in English and Hindi | Code built; needs Meta account and template approval |
| S-7 | Customer opt-out by replying STOP (or "band karo") | Built |
| S-8 | Merchant dashboard with sign-in by a code sent on WhatsApp | Built |
| S-9 | Monthly subscription for PayRemind's own fee via Razorpay, with GST invoices | Built; needs Razorpay account |
| S-10 | Draft privacy policy, terms and data processing agreement | Drafts written; need a lawyer |
| S-11 | Hosting on AWS in Mumbai (ap-south-1) | Planned for M5, not built |

### 5.2 Out of scope for the beta

- Live sync with Tally (XML or ODBC); only file upload.
- Languages other than English and Hindi.
- Automatic payment matching from bank statements (the merchant marks invoices paid).
- Collecting or holding money on behalf of merchants.
- A mobile app.
- A CA view across many client businesses.
- Public self-service sign-up (the operator invites each business).

## 6. Business rules

| # | Rule | Why |
|---|---|---|
| BR-1 | Money always goes directly from the customer's UPI app to the merchant's own UPI ID. PayRemind never receives, holds or forwards customer payments. | Keeps PayRemind out of payment-aggregator regulation. **⚖ Verify** that this keeps PayRemind outside RBI payment aggregator rules. |
| BR-2 | A customer who replies STOP is never messaged again by any merchant on PayRemind. | Respect consent; WhatsApp policy requires honouring opt-outs; all merchants share one sender number. |
| BR-3 | At most one reminder per invoice per step; never more than one message a day per invoice. | Avoid spam and Meta quality penalties. |
| BR-4 | No reminders for paid invoices, for customers without a valid Indian mobile number, or while a promise to pay is active. | Politeness and accuracy. |
| BR-5 | Reminders stop when the merchant's trial ends or their subscription is halted, paused or cancelled. | Only paying (or trial) merchants consume WhatsApp costs. |
| BR-6 | Each merchant's data is visible only to that merchant. | Confidentiality; DPDP processor duties. |
| BR-7 | PayRemind is a data processor; the merchant is the data fiduciary for their customers' data. | Matches the DPA draft. **⚖ Verify** the DPDP role split. |
| BR-8 | Plans: Starter ₹999 a month and Growth ₹2,499 a month, plus GST; 30-day free trial by default. | Pricing hypothesis for the beta. |
| BR-9 | GST on PayRemind's own invoices: CGST + SGST for buyers in Karnataka, IGST otherwise, once PayRemind is GST-registered. | **⚖ Verify** registration timing, SAC code 998314 and invoice format with a CA. |

## 7. Success measures for the beta

| Measure | Target (to be refined with real data) |
|---|---|
| Merchants onboarded | 10–20 invited businesses |
| Weekly active merchants | Most invited merchants upload at least monthly |
| Reminder delivery | Very few failed sends per daily run |
| Opt-out rate | Low; a rising rate means messages feel like spam |
| Paid within 15 days of due date | Higher than the merchant's own baseline (ask them) |
| Trial to paid conversion | At least a few conversions |
| Monthly hosting cost | Within the $50–150 budget, alarms at $50 and $100 |
| Security incidents | None; any incident handled within the 6-hour CERT-In window |

## 8. Assumptions

- Merchants can export an outstanding list with customer name, invoice number, due date and
  balance. Phone numbers are often missing and are optional.
- Meta approves the `payment_reminder_v1` utility template in English and Hindi, and the
  `login_code_v1` authentication template.
- Merchants already have a UPI ID that accepts payments.
- The operator runs the daily job and handles support during the beta.

## 9. Constraints

- Built in Python by one person at 30–60 minutes a day.
- Low running cost; no NAT gateways or always-on servers unless they are needed.
- Data hosted in India (ap-south-1).
- WhatsApp business-initiated messages must use approved templates and cost money per message.
  **⚖ Verify** current Meta pricing for utility and authentication messages in India.

## 10. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Meta rejects templates or limits the number | No reminders, no login | Submit early; keep text factual and utility-only; fallback sender number |
| Customers see reminders as spam | Opt-outs, low quality rating, number blocked | Few steps, polite text, STOP honoured for all merchants |
| Payment regulation applies after all | Could need a licence or a partner | Never touch money (BR-1); get professional confirmation |
| Data leak between merchants | Loss of trust, legal exposure | Tenant-scoped queries, isolation tests as a launch gate |
| Owner's time is limited (exams, relocation) | Slow progress | Small milestones; invite-only; cheap, low-maintenance hosting |
| GST or DPDP mistakes | Penalties | CA and lawyer review before charging money |

## 11. Approval

| Name | Role | Decision | Date |
|---|---|---|---|
| Hari | Owner | | |
