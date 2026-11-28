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
