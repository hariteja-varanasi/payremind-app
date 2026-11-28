# PayRemind AWS beta (Mumbai, ap-south-1)

For a short throwaway test on your own account (no domain, about $0.10/hour, destroy the same day), see [TEST-DEPLOY.md](TEST-DEPLOY.md).

For a demo stack whose data lives in Supabase Postgres (dev, test, staging and prod schemas; AWS up only during the demo), see [DEMO.md](DEMO.md).

Terraform in `infra/terraform` creates everything below. **Nothing has been applied.** Review
the cost estimate and the plan output before running `terraform apply`.

## Architecture

```
Customer / merchant ──HTTPS──> CloudFront (+ WAF: IP reputation, OWASP common rules,
                                 known-bad-inputs, India-only except /webhooks/, login and
                                 global rate limits, HSTS)
                                   │  HTTPS + secret X-Origin-Verify header
                                   ▼
                     ALB (accepts CloudFront IP ranges only; 403 without the header)
                                   │  :8000
                                   ▼
                     ECS Fargate task, ARM, 0.25 vCPU / 0.5 GB, read-only root FS
                       │ public IP for outbound only (WhatsApp, Razorpay); no inbound
                       ▼
                     RDS Postgres 16, db.t4g.micro, private subnets, encrypted,
                     TLS forced, 7-day backups + PITR, deletion protection

EventBridge Scheduler ── 09:30 IST ──> one-off Fargate task: `payremind run-reminders`
Logs: app + VPC flow (rejects) in CloudWatch 365 days; ALB access logs + CloudTrail in S3
365 days (CERT-In asks for 180). GuardDuty findings (medium+) and budget alerts go by email.
Secrets: SSM Parameter Store SecureString; DB password managed and rotated by RDS.
```

No NAT gateway (saves ~$35/month): the app runs in public subnets with a public IP, but its
security group only accepts traffic from the ALB. The database has no internet route at all.

## Monthly cost estimate (beta, low traffic)

Rough figures. Check them in the [AWS Pricing Calculator](https://calculator.aws/) before applying.

| Item | Est. USD/month |
|---|---|
| Fargate app task, 0.25 vCPU + 0.5 GB ARM, always on | ~7 |
| Daily reminder task (~2 min/day) | < 0.10 |
| Application Load Balancer (hours + low LCU use) | ~18–22 |
| Public IPv4 addresses (ALB ×2, task ×1) at $0.005/hour each | ~11 |
| RDS db.t4g.micro, single-AZ ([~$15/month in Mumbai](https://www.bytebase.com/dbcost/rds/instance/db.t4g.micro/)) | ~15 |
| RDS gp3 storage 20 GB + backups | ~3 |
| WAF: web ACL $5 + 6 rules × $1 + $0.60 per million requests ([pricing](https://aws.amazon.com/waf/pricing)) | ~11–12 |
| CloudFront (always-free tier covers beta traffic) | 0–1 |
| CloudWatch Logs, VPC flow logs (rejects only) | 1–3 |
| GuardDuty (30-day free trial first) | 2–5 |
| CloudTrail (first management trail free) + S3 log storage | < 1 |
| Secrets Manager (RDS secret), Route 53 zone, ECR storage | ~1 |
| SSM parameters, ACM certificates, AWS-managed KMS keys, 2 budgets | 0 |
| **Total** | **~70–82 USD (about ₹6,000–7,000)** |

- AWS India bills add 18% GST, which you can claim back once you're GST-registered.
- A domain is extra (about ₹800/year for a `.in`).
- AWS has announced a new WAF pricing model from 1 Feb 2027, so re-check this line then.
- **Biggest levers:** the ALB plus its IPs cost ~$30. A single EC2 instance behind CloudFront
  would cost ~$25–30 in total, but then you patch the OS and run backups yourself. I don't
  recommend that for a payments-adjacent app.

A budget alarm emails you at 50% and 100% of `monthly_budget_usd` (default $100), and when
the month is forecast to go over.

## Deploy runbook

Prerequisites: AWS account with root MFA and an admin user in IAM Identity Center, AWS CLI v2,
Terraform ≥ 1.10, Docker with buildx, and a domain whose DNS is in a Route 53 hosted zone.

```bash
# 0. One-off: state bucket (then copy backend.tf.example to backend.tf)
aws s3api create-bucket --bucket payremind-tfstate-<account-id> --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1
aws s3api put-bucket-versioning --bucket payremind-tfstate-<account-id> --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket payremind-tfstate-<account-id> \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in domain, zone id, email, address
terraform init
terraform plan -out beta.plan                  # review: ~90 resources; only CloudFront is public
terraform apply beta.plan                      # stage 1: app at 0 tasks, daily job off

# 1. Real secrets (never in git or Terraform state)
for k in whatsapp_token whatsapp_phone_number_id whatsapp_app_secret razorpay_key_id \
         razorpay_key_secret razorpay_webhook_secret razorpay_plan_starter razorpay_plan_growth; do
  read -rsp "$k: " v; echo
  aws ssm put-parameter --name /payremind/beta/$k --type SecureString --overwrite --value "$v"
done
# supplier_gstin: leave "unset" until you're GST-registered

# 2. Build and push the image (ARM64)
ECR=$(terraform output -raw ecr_repository_url); SHA=$(git rev-parse --short HEAD)
aws ecr get-login-password | docker login --username AWS --password-stdin ${ECR%/*}
docker buildx build --platform linux/arm64 -t $ECR:$SHA --push ../..
terraform apply -var image_tag=$SHA            # task definition now points at the image

# 3. Migrate the database and invite the first business (one-off tasks)
run() { aws ecs run-task --cluster $(terraform output -raw ecs_cluster) \
  --task-definition $(terraform output -raw task_definition) --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$(terraform output -raw public_subnets)],securityGroups=[$(terraform output -raw app_security_group)],assignPublicIp=ENABLED}" \
  --overrides "{\"containerOverrides\":[{\"name\":\"app\",\"command\":$1}]}"; }
run '["payremind","migrate"]'
run '["payremind","invite","--name","First Traders","--upi","first@okaxis","--payee","First Traders","--owner-phone","98450XXXXX","--trial-days","0"]'
# The invite prints an API token to the logs. The dashboard doesn't need it, so delete that log stream.

# 4. Go live for invited users
terraform apply -var image_tag=$SHA -var app_desired_count=1
curl -s https://<domain>/health                 # {"status":"ok"}
# Set the webhook URLs from `terraform output` in Meta (verify token: SSM whatsapp_verify_token)
# and in Razorpay (secret = razorpay_webhook_secret). Once the templates are approved:
terraform apply -var image_tag=$SHA -var app_desired_count=1 -var reminders_enabled=true
```

Deploying a new version means pushing a new image tag and running `terraform apply -var image_tag=<sha>`.
ECS rolls it out and rolls back automatically if health checks fail.

## Before opening to the public (launch gates)

- [ ] OWASP ZAP baseline scan against the beta URL: no high or critical findings
- [ ] Restore test: restore the latest RDS snapshot to a new instance, run `payremind migrate`, spot-check data
- [ ] Load test of the reminder run and dashboard
- [ ] 6-hour CERT-In incident runbook written; GuardDuty email tested
- [ ] Lawyer-reviewed privacy policy, terms and DPA; CA-reviewed GST invoice
- [ ] Consider Multi-AZ RDS and customer-managed KMS keys (see trade-offs)

## Security trade-offs accepted for the beta

`infra/terraform/.checkov.yaml` lists every Checkov rule that's skipped and why. The main ones:
- Single-AZ database (cost)
- AWS-managed encryption keys instead of customer-managed keys (cost and complexity)
- Public IP on the app task instead of a NAT gateway
- No full WAF logs (sampled requests are kept)

All other checks pass: 197 passed, 0 failed.

## Offline checks (no AWS credentials)

```bash
terraform fmt -check -recursive && terraform init -backend=false && terraform validate
terraform test           # mocked plan: safe defaults (0 tasks, job off, private encrypted DB, IST, logs)
checkov -d . --config-file .checkov.yaml
```
