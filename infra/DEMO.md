# Demo stack: app on AWS for the demo, data kept in Supabase

The app runs on AWS only while you demo it and is destroyed afterwards. The data lives in a
Supabase Postgres project that you keep between demos. Each environment has its own schema:

| Schema    | Contents                         | Used by                          |
|-----------|----------------------------------|----------------------------------|
| `dev`     | Dummy demo business              | Your own trials                  |
| `test`    | Dummy demo business              | Automated or manual testing      |
| `staging` | Dummy demo business              | Demos to other people            |
| `prod`    | **Empty.** Real customers later  | The real beta, never demo mode   |

Safety rules built into the code:

- Demo mode refuses to start with real WhatsApp or Razorpay keys, and refuses the `prod`
  schema. Terraform refuses `demo_mode` on `prod`, or without `ephemeral = true`.
- `seed-demo` only runs in demo mode and, on Postgres, only into `dev`, `test` or `staging`.
  It deletes and recreates only the demo business. Nothing else in the schema is touched.
- No WhatsApp messages are sent. The demo shows them on an "Outbox" page instead.
- Row-level security is on for every table in every schema, so Supabase's public Data API
  can't read them. Turn the Data API off as well (step 1).

**Cost:** about **$0.07–0.09 per hour** on AWS while it's up. RDS isn't created, so a
3–4 hour demo is roughly $0.30. Supabase free tier is $0. A free project pauses after about a
week with no activity. Restore it from the Supabase dashboard before a demo, which takes a
few minutes.

## 1. Supabase (once)

1. Create a project in region **South Asia (Mumbai) `ap-south-1`**. Save the database
   password in your password manager.
2. **Project Settings → Data API**: turn it off (PayRemind doesn't use it).
3. **Connect** (top bar) → **Session pooler** and copy the URI. It looks like
   `postgresql://postgres.<ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres`.
   Use the session pooler (port 5432) because it works over IPv4. The direct connection
   is IPv6 only. Don't paste this URL into chat, tickets or git.

## 2. Create the schemas and the dummy data (once, from your laptop)

The image you build for AWS can do this locally. Keep the URL in an environment variable
that you type at a hidden prompt:

```bash
read -rs PAYREMIND_DATABASE_URL; export PAYREMIND_DATABASE_URL   # paste the session pooler URI
docker build -t payremind:local .
r() { docker run --rm -e PAYREMIND_DATABASE_URL "$@" payremind:local; }

r payremind migrate --schemas dev,test,staging,prod     # creates all four, with RLS
for s in dev test staging; do
  r -e PAYREMIND_DB_SCHEMA=$s -e PAYREMIND_DEMO_MODE=true payremind seed-demo
done
```

`prod` now has the tables but no rows. Run `migrate --schemas ...` again after any upgrade
that adds migrations. It's safe to repeat.

## 3. Spin up the demo (about 15 minutes)

AWS login is the same as in [TEST-DEPLOY.md](TEST-DEPLOY.md) step 1 (`aws sso login`).

```bash
cd infra/terraform
cp demo.tfvars.example demo.tfvars     # set alert_email; on an Intel/AMD laptop add cpu_architecture = "X86_64"
terraform init
terraform plan -var-file demo.tfvars -out demo.plan     # review before applying
terraform apply demo.plan

# Give the app the Supabase URL (stored encrypted in SSM, never in Terraform state)
aws ssm put-parameter --region ap-south-1 --overwrite --type SecureString \
  --name "$(terraform output -raw database_url_parameter)" --value "$PAYREMIND_DATABASE_URL"

ECR=$(terraform output -raw ecr_repository_url); SHA=$(git rev-parse --short HEAD)
PLATFORM=linux/arm64                    # linux/amd64 if you set X86_64
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin ${ECR%/*}
docker buildx build --platform $PLATFORM -t $ECR:$SHA --push ../..
terraform apply -var-file demo.tfvars -var image_tag=$SHA -var app_desired_count=1
```

Optional: refresh the demo data first so the due dates are relative to today. Run
`seed-demo` for the schema you're demoing (step 2 loop, or just `staging`).

## 4. Give the demo

Open `$(terraform output -raw app_url)/login` and click **Open the demo business**. Then show:

1. **Dashboard**: what's owed, ageing buckets, overdue and due-soon invoices.
2. **Upload**: a Tally or Excel export (any CSV with party, mobile, invoice, due date, amount).
3. **Outbox**: the WhatsApp reminders customers would receive in English or Hindi, each with a
   pay link. Open one to show the UPI pay page and QR.
4. **Promises**: a customer's promise to pay pauses their reminders.
5. **Billing**: the plan and a GST invoice.

To allow someone outside India, add their country code to `allowed_countries` and apply again.

## 5. Destroy (always)

```bash
terraform destroy -var-file demo.tfvars
```

This removes everything on AWS. The Supabase data stays for next time.

## Real customer data (`prod`)

Real customers' names and phone numbers are personal data under India's DPDP Act. Before
anything goes into `prod`:

- Use a paid Supabase plan (Pro, about $25/month) for daily backups and no pausing, or the
  RDS setup in [README.md](README.md).
- Sign the data-processing terms with each business ([docs/legal/dpa.md](../docs/legal/dpa.md)).
- Use a normal (non-ephemeral, non-demo) stack with the domain, `db_schema = "prod"` and its
  own database password. Don't reuse the demo stack against `prod`.
- Better still, keep `prod` in a separate Supabase project so a demo credential can never
  reach it.
