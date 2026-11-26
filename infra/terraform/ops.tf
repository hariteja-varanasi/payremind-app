# --- Daily reminder job: 09:30 IST, runs `payremind run-reminders` as a one-off task ---
resource "aws_iam_role" "scheduler" {
  name = "payremind-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "ecs:RunTask"
        Resource  = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:task-definition/${aws_ecs_task_definition.app.family}:*"
        Condition = { ArnEquals = { "ecs:cluster" = aws_ecs_cluster.main.arn } }
      },
      {
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [aws_iam_role.execution.arn, aws_iam_role.task.arn]
      },
    ]
  })
}

resource "aws_scheduler_schedule" "reminders" {
  name                         = "payremind-daily-reminders"
  state                        = var.reminders_enabled ? "ENABLED" : "DISABLED"
  schedule_expression          = "cron(30 9 * * ? *)"
  schedule_expression_timezone = "Asia/Kolkata"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn
    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.app.arn
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = aws_subnet.public[*].id
        security_groups  = [aws_security_group.app.id]
        assign_public_ip = true
      }
    }
    input = jsonencode({
      containerOverrides = [{ name = "app", command = ["payremind", "run-reminders"] }]
    })
    retry_policy {
      maximum_retry_attempts = 2 # safe: reminders are idempotent
    }
  }
}

# --- Audit and threat detection ---
resource "aws_cloudtrail" "main" {
  name                          = "payremind"
  s3_bucket_name                = aws_s3_bucket.logs.id
  s3_key_prefix                 = "cloudtrail"
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  depends_on                    = [aws_s3_bucket_policy.logs]
}

resource "aws_guardduty_detector" "main" {
  enable                       = true
  finding_publishing_frequency = "FIFTEEN_MINUTES"
}

# --- Alerts ---
resource "aws_sns_topic" "alerts" {
  name = "payremind-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.alerts.arn
    }]
  })
}

# Email GuardDuty findings of severity >= 4 (medium and above).
resource "aws_cloudwatch_event_rule" "guardduty" {
  name = "payremind-guardduty-findings"
  event_pattern = jsonencode({
    source        = ["aws.guardduty"]
    "detail-type" = ["GuardDuty Finding"]
    detail        = { severity = [{ numeric = [">=", 4] }] }
  })
}

resource "aws_cloudwatch_event_target" "guardduty" {
  rule = aws_cloudwatch_event_rule.guardduty.name
  arn  = aws_sns_topic.alerts.arn
}

resource "aws_budgets_budget" "monthly" {
  name         = "payremind-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
