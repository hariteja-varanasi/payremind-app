# Offline plan with mocked providers: `terraform test` (no AWS credentials, nothing created).
mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-south-1a", "ap-south-1b", "ap-south-1c"] }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_elb_service_account" {
    defaults = { arn = "arn:aws:iam::718504428378:root" }
  }
  mock_resource "aws_db_instance" {
    defaults = {
      address = "db.example.internal"
      master_user_secret = [{
        secret_arn    = "arn:aws:secretsmanager:ap-south-1:123456789012:secret:rds-db-abc"
        kms_key_id    = "k"
        secret_status = "active"
      }]
    }
  }
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:ap-south-1:123456789012:certificate/abc"
    }
  }
}

mock_provider "aws" {
  alias = "us_east_1"
  mock_resource "aws_wafv2_web_acl" {
    defaults = { arn = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/payremind/abc" }
  }
}

mock_provider "random" {}

variables {
  domain_name    = "app.example.in"
  hosted_zone_id = "Z0123456789"
  alert_email    = "alerts@example.com"
}

run "defaults_are_safe" {
  command = plan

  assert {
    condition     = aws_ecs_service.app.desired_count == 0
    error_message = "App must start with 0 tasks until secrets are set"
  }
  assert {
    condition     = aws_scheduler_schedule.reminders.state == "DISABLED"
    error_message = "Daily job must start disabled"
  }
  assert {
    condition     = aws_db_instance.main.publicly_accessible == false && aws_db_instance.main.storage_encrypted
    error_message = "Database must be private and encrypted"
  }
  assert {
    condition     = aws_db_instance.main.deletion_protection
    error_message = "Database needs deletion protection"
  }
  assert {
    condition     = aws_scheduler_schedule.reminders.schedule_expression_timezone == "Asia/Kolkata"
    error_message = "Reminders must run on IST"
  }
  assert {
    condition     = aws_cloudwatch_log_group.app.retention_in_days >= 180
    error_message = "CERT-In needs 180 days of logs"
  }
  assert {
    condition     = var.region == "ap-south-1"
    error_message = "Data must stay in Mumbai"
  }
}

run "stage_two" {
  command = plan
  variables {
    app_desired_count = 1
    reminders_enabled = true
    image_tag         = "abc1234"
  }
  assert {
    condition     = aws_scheduler_schedule.reminders.state == "ENABLED"
    error_message = "Daily job should enable"
  }
}

run "ephemeral_test_mode_without_domain" {
  command = plan
  variables {
    domain_name    = ""
    hosted_zone_id = ""
    ephemeral      = true
  }
  assert {
    condition     = length(aws_acm_certificate.viewer) == 0 && length(aws_route53_record.app) == 0
    error_message = "No certificates or DNS without a domain"
  }
  assert {
    condition     = length(aws_lb_listener.http) == 1 && length(aws_lb_listener.https) == 0
    error_message = "Test mode uses the HTTP origin listener"
  }
  assert {
    condition     = aws_db_instance.main.deletion_protection == false && aws_db_instance.main.skip_final_snapshot
    error_message = "Test stack must be fully destroyable"
  }
  assert {
    condition     = aws_lb.app.enable_deletion_protection == false && aws_s3_bucket.logs.force_destroy
    error_message = "Test stack must be fully destroyable"
  }
  assert {
    condition     = aws_cloudfront_distribution.app.viewer_certificate[0].cloudfront_default_certificate
    error_message = "Test mode uses the *.cloudfront.net certificate"
  }
}

run "domain_required_outside_test_mode" {
  command = plan
  variables {
    domain_name = ""
    ephemeral   = false
  }
  expect_failures = [var.domain_name]
}
