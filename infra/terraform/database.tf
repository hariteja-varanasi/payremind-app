# Skipped when external_database = true (e.g. Supabase): the app gets a URL from SSM instead.
locals {
  use_rds = !var.external_database
}

resource "aws_db_subnet_group" "main" {
  count      = local.use_rds ? 1 : 0
  name       = "payremind-${var.environment}"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "pg16" {
  count  = local.use_rds ? 1 : 0
  name   = "payremind-pg16"
  family = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "1000" # log queries slower than 1s
  }
}

resource "aws_db_instance" "main" {
  # checkov:skip=CKV_AWS_293:On by default; off only when ephemeral = true so tests can be destroyed
  count                           = local.use_rds ? 1 : 0
  identifier                      = "payremind-${var.environment}"
  engine                          = "postgres"
  engine_version                  = "16"
  instance_class                  = var.db_instance_class
  allocated_storage               = 20
  max_allocated_storage           = 50
  storage_type                    = "gp3"
  storage_encrypted               = true
  db_name                         = "payremind"
  username                        = "payremind"
  manage_master_user_password     = true # RDS keeps the password in Secrets Manager and rotates it
  db_subnet_group_name            = aws_db_subnet_group.main[0].name
  vpc_security_group_ids          = [aws_security_group.db.id]
  parameter_group_name            = aws_db_parameter_group.pg16[0].name
  publicly_accessible             = false
  multi_az                        = false # beta; switch on before public launch if budget allows
  backup_retention_period         = 7
  backup_window                   = "20:00-21:00" # 01:30-02:30 IST
  maintenance_window              = "sun:21:00-sun:22:00"
  auto_minor_version_upgrade      = true
  copy_tags_to_snapshot           = true
  deletion_protection             = !var.ephemeral
  skip_final_snapshot             = var.ephemeral
  final_snapshot_identifier       = "payremind-${var.environment}-final"
  performance_insights_enabled    = true # 7-day retention is free
  enabled_cloudwatch_logs_exports = ["postgresql"]
}
