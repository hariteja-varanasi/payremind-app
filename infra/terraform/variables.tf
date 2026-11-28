variable "region" {
  type    = string
  default = "ap-south-1" # Mumbai: data stays in India
}

variable "environment" {
  type    = string
  default = "beta"
}

variable "domain_name" {
  description = "Public hostname, e.g. app.payremind.in. Empty = use the CloudFront default URL (test mode only)"
  type        = string
  default     = ""
  validation {
    condition     = var.domain_name != "" || var.ephemeral
    error_message = "domain_name is required unless ephemeral = true."
  }
}

variable "hosted_zone_id" {
  description = "Route 53 hosted zone that contains domain_name (not needed without a domain)"
  type        = string
  default     = ""
  validation {
    condition     = var.domain_name == "" || var.hosted_zone_id != ""
    error_message = "hosted_zone_id is required when domain_name is set."
  }
}

variable "ephemeral" {
  description = <<-EOT
    Throwaway test stack: no deletion protection or final snapshot (so `terraform destroy`
    removes everything), and WhatsApp messages plus login codes are written to the app log
    instead of being sent. Never use for real customer data.
  EOT
  type        = bool
  default     = false
}

variable "alert_email" {
  description = "Gets budget and security alerts"
  type        = string
}

variable "monthly_budget_usd" {
  type    = number
  default = 100
}

variable "image_tag" {
  description = "ECR image tag to run (use the git commit SHA)"
  type        = string
  default     = "bootstrap"
}

variable "app_desired_count" {
  description = "Keep 0 until secrets are set and an image is pushed; then 1"
  type        = number
  default     = 0
}

variable "reminders_enabled" {
  description = "Turn on the 09:30 IST daily reminder job"
  type        = bool
  default     = false
}

variable "allowed_countries" {
  description = "Viewer countries allowed (webhooks are exempt so Meta and Razorpay can reach us)"
  type        = list(string)
  default     = ["IN"]
}

variable "supplier_name" {
  type    = string
  default = "PayRemind"
}

variable "supplier_state_code" {
  type    = string
  default = "29"
}

variable "supplier_address" {
  type    = string
  default = ""
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "enable_flow_logs" {
  type    = bool
  default = true
}

variable "cpu_architecture" {
  description = "ARM64 (cheaper, Graviton) or X86_64 (match an Intel/AMD laptop to skip emulated builds)"
  type        = string
  default     = "ARM64"
  validation {
    condition     = contains(["ARM64", "X86_64"], var.cpu_architecture)
    error_message = "cpu_architecture must be ARM64 or X86_64."
  }
}

variable "external_database" {
  description = <<-EOT
    Use a Postgres outside AWS (e.g. Supabase) instead of creating RDS. Set its URL in SSM
    at /payremind/<environment>/database_url with `aws ssm put-parameter` (never in tfvars).
  EOT
  type        = bool
  default     = false
}

variable "db_schema" {
  description = "Postgres schema this stack uses: dev, test, staging or prod. Empty = default."
  type        = string
  default     = ""
  validation {
    condition     = var.db_schema == "" || can(regex("^[a-z_][a-z0-9_]{0,30}$", var.db_schema))
    error_message = "db_schema must be a lowercase Postgres name such as dev, test, staging or prod."
  }
}

variable "demo_mode" {
  description = <<-EOT
    Demo stack: one-click demo login, outbox page and DEMO banner. The app refuses to start
    with real WhatsApp or Razorpay keys. Needs ephemeral = true and never the prod schema.
  EOT
  type        = bool
  default     = false
  validation {
    condition     = !var.demo_mode || var.ephemeral
    error_message = "demo_mode needs ephemeral = true."
  }
  validation {
    condition     = !var.demo_mode || !contains(["prod", "public"], var.db_schema)
    error_message = "demo_mode can't use the prod or public schema; use dev, test or staging."
  }
  validation {
    condition     = !var.demo_mode || !var.reminders_enabled
    error_message = "demo_mode keeps the daily reminder job off."
  }
}
