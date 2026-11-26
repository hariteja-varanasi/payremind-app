terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  # State holds generated secrets. Use the S3 backend in backend.tf.example (encrypted,
  # versioned, lockfile) rather than keeping terraform.tfstate on a laptop.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "payremind", Environment = var.environment, ManagedBy = "terraform" }
  }
}

# CloudFront certificates and CloudFront-scoped WAF must live in us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = { Project = "payremind", Environment = var.environment, ManagedBy = "terraform" }
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }
