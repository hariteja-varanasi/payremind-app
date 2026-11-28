# DNS + certificates + CloudFront + WAF. Viewers reach https://<domain_name>; CloudFront talks
# to the ALB at origin.<domain_name> and adds a secret header the ALB checks.
locals {
  use_domain    = var.domain_name != ""
  origin_domain = "origin.${var.domain_name}"
  public_host   = local.use_domain ? var.domain_name : aws_cloudfront_distribution.app.domain_name
  public_url    = "https://${local.public_host}"
}

# --- Certificates ---
resource "aws_acm_certificate" "origin" {
  count             = local.use_domain ? 1 : 0
  domain_name       = local.origin_domain
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate" "viewer" {
  count             = local.use_domain ? 1 : 0
  provider          = aws.us_east_1
  domain_name       = var.domain_name
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

# Static keys so planning works before the certificates exist (one name per certificate).
resource "aws_route53_record" "cert_validation" {
  for_each = local.use_domain ? {
    origin = aws_acm_certificate.origin[0]
    viewer = aws_acm_certificate.viewer[0]
  } : {}
  zone_id         = var.hosted_zone_id
  name            = one(each.value.domain_validation_options).resource_record_name
  type            = one(each.value.domain_validation_options).resource_record_type
  records         = [one(each.value.domain_validation_options).resource_record_value]
  ttl             = 300
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "origin" {
  count                   = local.use_domain ? 1 : 0
  certificate_arn         = aws_acm_certificate.origin[0].arn
  validation_record_fqdns = [aws_route53_record.cert_validation["origin"].fqdn]
}

resource "aws_acm_certificate_validation" "viewer" {
  count                   = local.use_domain ? 1 : 0
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.viewer[0].arn
  validation_record_fqdns = [aws_route53_record.cert_validation["viewer"].fqdn]
}

resource "aws_route53_record" "origin" {
  count   = local.use_domain ? 1 : 0
  zone_id = var.hosted_zone_id
  name    = local.origin_domain
  type    = "A"
  alias {
    name                   = aws_lb.app.dns_name
    zone_id                = aws_lb.app.zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "app" {
  count   = local.use_domain ? 1 : 0
  zone_id = var.hosted_zone_id
  name    = var.domain_name
  type    = "A"
  alias {
    name                   = aws_cloudfront_distribution.app.domain_name
    zone_id                = aws_cloudfront_distribution.app.hosted_zone_id
    evaluate_target_health = false
  }
}

# --- WAF (CloudFront scope lives in us-east-1) ---
resource "aws_wafv2_web_acl" "app" {
  provider = aws.us_east_1
  name     = "payremind-${var.environment}"
  scope    = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "ip-reputation"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "common"
    priority = 2
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
        # Invoice uploads are up to 5 MB; the app enforces its own size limit.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "known-bad-inputs"
    priority = 3
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "geo-india-only"
    priority = 4
    action {
      block {}
    }
    statement {
      and_statement {
        statement {
          not_statement {
            statement {
              geo_match_statement {
                country_codes = var.allowed_countries
              }
            }
          }
        }
        statement {
          not_statement {
            statement {
              byte_match_statement {
                search_string         = "/webhooks/"
                positional_constraint = "STARTS_WITH"
                field_to_match {
                  uri_path {}
                }
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "geo"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "login-rate-limit"
    priority = 5
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit                 = 20 # per IP per 5 minutes
        aggregate_key_type    = "IP"
        evaluation_window_sec = 300
        scope_down_statement {
          byte_match_statement {
            search_string         = "/login"
            positional_constraint = "STARTS_WITH"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "login-rate"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "global-rate-limit"
    priority = 6
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit                 = 1000
        aggregate_key_type    = "IP"
        evaluation_window_sec = 300
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "global-rate"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "payremind"
    sampled_requests_enabled   = true
  }
}

# --- CloudFront ---
data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_response_headers_policy" "hsts" {
  name = "payremind-hsts"
  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true # directive only; hstspreload.org submission is a separate manual step
      override                   = true
    }
  }
}

resource "aws_cloudfront_distribution" "app" {
  # checkov:skip=CKV_AWS_174:TLS 1.2 minimum with a domain; the *.cloudfront.net certificate in test mode cannot set it
  enabled         = true
  is_ipv6_enabled = true
  aliases         = local.use_domain ? [var.domain_name] : []
  price_class     = "PriceClass_200" # includes India edge locations
  web_acl_id      = aws_wafv2_web_acl.app.arn
  http_version    = "http2and3"

  origin {
    origin_id   = "alb"
    domain_name = local.use_domain ? local.origin_domain : aws_lb.app.dns_name
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = local.use_domain ? "https-only" : "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_secret.result
    }
  }

  default_cache_behavior {
    target_origin_id           = "alb"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_except_host.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.hsts.id
    compress                   = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none" # geo filtering is done in WAF so webhooks stay reachable
    }
  }

  viewer_certificate {
    # With a domain: our ACM certificate. Test mode: CloudFront's *.cloudfront.net certificate.
    cloudfront_default_certificate = !local.use_domain
    acm_certificate_arn            = local.use_domain ? aws_acm_certificate_validation.viewer[0].certificate_arn : null
    ssl_support_method             = local.use_domain ? "sni-only" : null
    minimum_protocol_version       = local.use_domain ? "TLSv1.2_2021" : "TLSv1"
  }
}
