resource "aws_ecr_repository" "app" {
  name                 = "payremind"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.ephemeral
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 15 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 15 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/payremind/app"
  retention_in_days = 365 # CERT-In requires at least 180 days
}

resource "aws_ecs_cluster" "main" {
  name = "payremind-${var.environment}"
  setting {
    name  = "containerInsights"
    value = "disabled" # saves ~$3-5/month; turn on when debugging
  }
}

# --- IAM ---
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Used by ECS to pull the image and read secrets at start-up.
resource "aws_iam_role" "execution" {
  name               = "payremind-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_base" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameters"]
        Resource = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/payremind/${var.environment}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_db_instance.main.master_user_secret[0].secret_arn
      },
    ]
  })
}

# The app itself needs no AWS permissions.
resource "aws_iam_role" "task" {
  name               = "payremind-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# --- Task definition ---
locals {
  ssm_prefix = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/payremind/${var.environment}"
  secret_env = concat(
    [for name in local.manual_secrets : { name = "PAYREMIND_${upper(name)}", valueFrom = "${local.ssm_prefix}/${name}" }],
    [
      { name = "PAYREMIND_SECRET_KEY", valueFrom = aws_ssm_parameter.secret_key.arn },
      { name = "PAYREMIND_WHATSAPP_VERIFY_TOKEN", valueFrom = aws_ssm_parameter.verify_token.arn },
      { name = "PAYREMIND_DB_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" },
    ],
  )
  plain_env = [
    { name = "PAYREMIND_DB_HOST", value = aws_db_instance.main.address },
    { name = "PAYREMIND_DB_NAME", value = aws_db_instance.main.db_name },
    { name = "PAYREMIND_DB_USER", value = aws_db_instance.main.username },
    { name = "PAYREMIND_PUBLIC_BASE_URL", value = local.public_url },
    { name = "PAYREMIND_DEV_LOG_MESSAGES", value = var.ephemeral ? "true" : "false" },
    { name = "PAYREMIND_SUPPLIER_NAME", value = var.supplier_name },
    { name = "PAYREMIND_SUPPLIER_STATE_CODE", value = var.supplier_state_code },
    { name = "PAYREMIND_SUPPLIER_ADDRESS", value = var.supplier_address },
  ]
}

resource "aws_ecs_task_definition" "app" {
  family                   = "payremind"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    cpu_architecture        = var.cpu_architecture # ARM64 (Graviton) is ~20% cheaper
    operating_system_family = "LINUX"
  }
  # Writable /tmp (uploads over 1 MB spool to disk) while the root filesystem stays read-only.
  volume {
    name = "tmp"
  }
  container_definitions = jsonencode([{
    name                   = "app"
    image                  = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    portMappings           = [{ containerPort = 8000, protocol = "tcp" }]
    mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]
    environment            = local.plain_env
    secrets                = local.secret_env
    healthCheck = {
      command  = ["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')\""]
      interval = 30
      timeout  = 5
      retries  = 3
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "app"
      }
    }
  }])
}

resource "aws_ecs_service" "app" {
  name             = "payremind"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.app.arn
  desired_count    = var.app_desired_count
  launch_type      = "FARGATE"
  platform_version = "LATEST"
  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = true # outbound only: the app SG allows inbound from the ALB alone
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = 8000
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 30
  depends_on                         = [aws_lb_listener.https, aws_lb_listener.http]
}

# --- Load balancer (reachable only from CloudFront with the shared origin header) ---
resource "aws_s3_bucket" "logs" {
  bucket        = "payremind-logs-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.ephemeral
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id
  versioning_configuration {
    status = "Enabled" # protects audit logs from overwrite or deletion
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket     = aws_s3_bucket.logs.id
  depends_on = [aws_s3_bucket_versioning.logs]
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    expiration {
      days = 365 # comfortably above CERT-In's 180 days
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_elb_service_account" "main" {}

resource "aws_s3_bucket_policy" "logs" {
  bucket = aws_s3_bucket.logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AlbAccessLogs"
        Effect    = "Allow"
        Principal = { AWS = data.aws_elb_service_account.main.arn }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.logs.arn}/alb/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
      },
      {
        Sid       = "CloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.logs.arn
      },
      {
        Sid       = "CloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.logs.arn}/cloudtrail/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = { StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" } }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.logs.arn, "${aws_s3_bucket.logs.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })
}

resource "aws_lb" "app" {
  # checkov:skip=CKV_AWS_150:On by default; off only when ephemeral = true so tests can be destroyed
  # checkov:skip=CKV2_AWS_20:Only CloudFront can reach the ALB; viewers are redirected to HTTPS at CloudFront
  name                       = "payremind-${var.environment}"
  load_balancer_type         = "application"
  internal                   = false
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  drop_invalid_header_fields = true
  enable_deletion_protection = !var.ephemeral
  idle_timeout               = 60
  access_logs {
    bucket  = aws_s3_bucket.logs.id
    prefix  = "alb"
    enabled = true
  }
  depends_on = [aws_s3_bucket_policy.logs]
}

resource "aws_lb_target_group" "app" {
  name                 = "payremind-app"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 15
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "https" {
  count             = local.use_domain ? 1 : 0
  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.origin[0].certificate_arn
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }
}

# Test mode only (no domain, so no certificate for the origin): CloudFront reaches the ALB over
# HTTP inside AWS's network. Still limited to CloudFront ranges plus the secret header.
resource "aws_lb_listener" "http" {
  # checkov:skip=CKV_AWS_2:Test mode only (no domain, so no origin certificate); CloudFront-only + secret header
  # checkov:skip=CKV_AWS_103:Test mode only, see above
  count             = local.use_domain ? 0 : 1
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }
}

locals {
  listener_arn = local.use_domain ? aws_lb_listener.https[0].arn : aws_lb_listener.http[0].arn
}

resource "aws_lb_listener_rule" "from_cloudfront" {
  listener_arn = local.listener_arn
  priority     = 10
  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [random_password.origin_secret.result]
    }
  }
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
