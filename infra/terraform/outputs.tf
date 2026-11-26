output "app_url" {
  value = "https://${var.domain_name}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "task_definition" {
  value = aws_ecs_task_definition.app.family
}

output "public_subnets" {
  value = join(",", aws_subnet.public[*].id)
}

output "app_security_group" {
  value = aws_security_group.app.id
}

output "whatsapp_webhook_url" {
  value = "https://${var.domain_name}/webhooks/whatsapp"
}

output "razorpay_webhook_url" {
  value = "https://${var.domain_name}/webhooks/razorpay"
}
