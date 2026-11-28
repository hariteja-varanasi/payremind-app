# App secrets live in SSM Parameter Store (SecureString, free tier). Terraform creates them
# with a placeholder; set real values with `aws ssm put-parameter --overwrite` (see DEPLOY.md).
# Terraform then ignores the value, so real secrets never enter state or git.
locals {
  manual_secrets = [
    "whatsapp_token",
    "whatsapp_phone_number_id",
    "whatsapp_app_secret",
    "razorpay_key_id",
    "razorpay_key_secret",
    "razorpay_webhook_secret",
    "razorpay_plan_starter",
    "razorpay_plan_growth",
    "supplier_gstin",
  ]
}

resource "aws_ssm_parameter" "manual" {
  for_each = toset(local.manual_secrets)
  name     = "/payremind/${var.environment}/${each.key}"
  type     = "SecureString"
  value    = "unset"
  lifecycle {
    ignore_changes = [value]
  }
}

# Generated once by Terraform (these are in state, so protect the state bucket).
resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "random_password" "verify_token" {
  length  = 32
  special = false
}

resource "random_password" "origin_secret" {
  length  = 40
  special = false
}

resource "aws_ssm_parameter" "secret_key" {
  name  = "/payremind/${var.environment}/secret_key"
  type  = "SecureString"
  value = random_password.secret_key.result
}

resource "aws_ssm_parameter" "verify_token" {
  name  = "/payremind/${var.environment}/whatsapp_verify_token"
  type  = "SecureString"
  value = random_password.verify_token.result
}

# External Postgres URL (Supabase session pooler). Placeholder only; set the real value with
# `aws ssm put-parameter --overwrite --type SecureString` so it never enters state or git.
resource "aws_ssm_parameter" "database_url" {
  count = var.external_database ? 1 : 0
  name  = "/payremind/${var.environment}/database_url"
  type  = "SecureString"
  value = "unset"
  lifecycle {
    ignore_changes = [value]
  }
}
