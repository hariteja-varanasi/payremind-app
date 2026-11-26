variable "region" {
  type    = string
  default = "ap-south-1" # Mumbai: data stays in India
}

variable "environment" {
  type    = string
  default = "beta"
}

variable "domain_name" {
  description = "Public hostname for the app, e.g. app.payremind.in"
  type        = string
}

variable "hosted_zone_id" {
  description = "Route 53 hosted zone that contains domain_name (used for certificates and DNS)"
  type        = string
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
