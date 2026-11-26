# PayRemind documentation

PayRemind sends WhatsApp payment reminders for Indian MSMEs. A merchant uploads an Excel or CSV
list of unpaid invoices, PayRemind works out what is overdue, and it sends polite reminders with a
link that pays the merchant's own UPI ID. PayRemind never holds money.

These documents describe the code on `main` as of 26 Nov 2026: the app at milestone M4 plus the M5 Terraform for AWS, which is written but not applied. Each one says
which parts are **built**, which are **planned**, and which are **gaps** found while writing it.

| Document | What it answers | Read it if you are… |
|---|---|---|
| [Business requirements (BRD)](01-business-requirements.md) | Why build this, for whom, what success looks like | deciding whether and what to build |
| [System requirements (SRS)](02-system-requirements.md) | What the system must do, as numbered, testable requirements | building or testing a feature |
| [Technical specification](03-technical-specification.md) | How it is built, and the decisions behind it | changing the code or the deployment |
| [Data model](04-data-model.md) | Tables, keys and how they relate (ERD) | writing a query or a migration |
| [API and routes](05-api-reference.md) | Every HTTP route and CLI command | integrating or testing |
| [Security and compliance](06-security-and-compliance.md) | Threats, controls, gaps, and the legal items to verify | reviewing risk |
| [Launch checklist](07-launch-checklist.md) | What must be true before beta and before public launch | planning the next weeks |
| [AWS infrastructure and runbook](../infra/README.md) | Terraform layout, cost estimate (~$70–82/month), deploy steps | deploying |

## Diagrams

Five diagrams live in [`diagrams/`](diagrams/). Each has an `.svg` (for viewing and slides) and a
`.drawio` file (open at app.diagrams.net to edit; Lucidchart can import it).

| Diagram | Shows |
|---|---|
| [System context](diagrams/01-system-context.svg) | Who PayRemind talks to, and that money goes straight to the merchant |
| [Components](diagrams/02-components.svg) | How the Python modules are layered |
| [Upload to payment](diagrams/03-data-flow.svg) | The life of one invoice, in 13 numbered steps |
| [Planned AWS deployment](diagrams/04-aws-planned.svg) | The M5 Terraform in ap-south-1. **Written, not applied** |
| [Trust boundaries](diagrams/05-trust-boundaries.svg) | Where untrusted input enters and what checks it |

All five come from [`diagrams/build.py`](diagrams/build.py). Change the coordinates or labels
there and run `python docs/diagrams/build.py` so the SVG and draw.io files stay in step.

## Other docs already in the repo

- [WhatsApp templates](whatsapp-templates.md): the exact template texts to submit to Meta.
- [Data Processing Agreement (draft)](legal/dpa.md): needs a lawyer's review.

## A note on legal, tax and payments statements

Statements in these documents about GST, the RBI, the DPDP Act, CERT-In or WhatsApp policy are
the author's reading, written for planning. They are **not legal or tax advice**. Each one is
marked **⚖ Verify** and is collected in the [launch checklist](07-launch-checklist.md) so a
lawyer or chartered accountant can check it before launch.

## Glossary

| Term | Meaning here |
|---|---|
| MSME | Micro, small or medium enterprise: the merchants who use PayRemind |
| Merchant / tenant / business | One PayRemind customer account. The code calls it a *tenant* |
| Customer / buyer | The merchant's own customer who owes money and receives reminders |
| UPI ID (VPA) | The merchant's payment address, such as `shop@okaxis` |
| Pay page | The public page at `/p/<token>` with a UPI button and QR code for one invoice |
| Reminder step / offset | Days relative to the due date when a reminder goes: −3, 0, +7, +15 |
| Promise to pay | A date the customer promised to pay by. Reminders pause until then |
| Opt-out | A customer replied STOP; no business will message that number again |
| Template | A WhatsApp message format that Meta must approve before it can be sent |
| Operator | Whoever runs PayRemind (today, Hari) using the `payremind` command line |
