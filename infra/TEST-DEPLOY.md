# Throwaway test deploy (your AWS account, a few hours, then destroy)

The whole stack runs in **test mode**:
- No domain: the app is served at CloudFront's `https://dxxxx.cloudfront.net` address.
- WhatsApp messages and login codes go to CloudWatch Logs instead of being sent, so no real
  phone gets a message. Razorpay stays off.
- No deletion protection, so `terraform destroy` removes everything.

**Cost:** about **$0.10–0.12 per hour** while it's up, so a 3–4 hour test is roughly $0.50.
Charges are prorated hourly (ALB, IPv4, RDS, WAF, Fargate). GuardDuty has a 30-day free
trial. Everything stops once you run `terraform destroy`.

## 1. Safe AWS login (no access keys)

Don't use the root user or long-lived access keys. In the AWS console, signed in as root
with MFA:

1. **IAM Identity Center** → Enable (free). Choose region **ap-south-1** if asked.
2. **Users** → Add user (for example `hari-admin`), with your email. Accept the invite and
   set a password plus MFA.
3. **Permission sets** → Create → Predefined → `AdministratorAccess`, session duration 4 hours.
4. **AWS accounts** → select your account → Assign users → `hari-admin` + that permission set.
5. On your laptop: `aws configure sso` (SSO start URL is on the Identity Center dashboard,
   region `ap-south-1`, profile name `payremind`). Then `export AWS_PROFILE=payremind` and
   check it with `aws sts get-caller-identity`.

The credentials are short-lived (4 hours) and stay on your laptop. Run `aws sso login` to
refresh them.

## 2. Deploy

```bash
cd infra/terraform
cp test.tfvars.example test.tfvars      # set alert_email; on an Intel/AMD laptop add cpu_architecture = "X86_64"
terraform init
terraform plan -var-file test.tfvars -out test.plan   # review it before applying
terraform apply test.plan               # ~15 min (CloudFront and RDS are the slow parts)

ECR=$(terraform output -raw ecr_repository_url); SHA=$(git rev-parse --short HEAD)
PLATFORM=linux/arm64                    # linux/amd64 if you set X86_64
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin ${ECR%/*}
docker buildx build --platform $PLATFORM -t $ECR:$SHA --push ../..
terraform apply -var-file test.tfvars -var image_tag=$SHA

run() { aws ecs run-task --region ap-south-1 --cluster $(terraform output -raw ecs_cluster) \
  --task-definition $(terraform output -raw task_definition) --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$(terraform output -raw public_subnets)],securityGroups=[$(terraform output -raw app_security_group)],assignPublicIp=ENABLED}" \
  --overrides "{\"containerOverrides\":[{\"name\":\"app\",\"command\":$1}]}" --query 'tasks[0].taskArn' --output text; }
run '["payremind","migrate"]'
sleep 90                                 # let the migration task finish
run '["payremind","invite","--name","Smoke Test Traders","--upi","smoke@okaxis","--payee","Smoke Test Traders","--owner-phone","9000000001","--trial-days","30"]'

terraform apply -var-file test.tfvars -var image_tag=$SHA -var app_desired_count=1
```

## 3. Test

```bash
URL=$(terraform output -raw app_url)
curl -s $URL/health
python ../../scripts/smoke_test.py --base-url $URL --phone 9000000001 \
  --cloudwatch-group $(terraform output -raw app_log_group)
```

The smoke test signs in with the logged code, uploads sample invoices, sets a promise, sends
reminders (they're only logged), opens a pay page, marks an invoice paid, and checks headers,
CSRF and webhook signature rejection. It's 32+ checks in all. You can also open `$URL/login`
in a browser and sign in with `9000000001`; the code is in CloudWatch → Log groups →
`/payremind/app`.

To check the daily job path: `run '["payremind","run-reminders"]'`, then look for
`businesses, … sent` in the log group.

## 4. Destroy (same day)

```bash
terraform destroy -var-file test.tfvars
```

Afterwards, check the console that nothing is left in ap-south-1 (ECS, RDS, Load Balancers,
CloudFront). CloudFront takes about 15 minutes to disable and delete.
