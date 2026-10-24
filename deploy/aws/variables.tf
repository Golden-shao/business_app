variable "aws_region" {
  type        = string
  description = "Choose a region explicitly after reviewing price and latency."
}

variable "ami_id" {
  type        = string
  description = "Explicit reviewed Ubuntu 24.04 x86 AMI in the chosen region; never a moving latest-image lookup."
  validation {
    condition     = can(regex("^ami-([a-f0-9]{8}|[a-f0-9]{17})$", var.ami_id))
    error_message = "Pin a region-specific Ubuntu 24.04 x86 AMI ID before planning."
  }
}

variable "domain" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.domain)) && !endswith(var.domain, ".example.com") && var.domain != "example.com" && !endswith(var.domain, ".test") && !endswith(var.domain, ".invalid") && !endswith(var.domain, ".local") && !endswith(var.domain, ".localhost")
    error_message = "Use a lowercase DNS hostname, without scheme, path or port."
  }
}

variable "acme_email" {
  type = string
  validation {
    condition     = can(regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$", var.acme_email))
    error_message = "Provide a contact email for certificate and budget alerts."
  }
}

variable "gateway_image" {
  type        = string
  description = "A publicly pullable, reviewed image pinned to its sha256 digest."
  validation {
    condition     = can(regex("^ghcr\\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$", var.gateway_image))
    error_message = "Provide an immutable ghcr.io image@sha256:digest reference."
  }
}

variable "release_commit" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{40}$", var.release_commit))
    error_message = "Pin the reviewed repository code using its complete 40-character commit SHA."
  }
}

variable "monthly_budget_usd" {
  type        = number
  description = "Account-wide alert budget, NOT a spending cap. Review before apply."
  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "An explicit positive monthly budget is required."
  }
}

variable "instance_type" {
  type    = string
  default = "t3.medium"
  validation {
    condition     = contains(["t3.medium", "t3.large"], var.instance_type)
    error_message = "This starter requires an x86 t3.medium or t3.large instance."
  }
}

variable "k3s_version" {
  type    = string
  default = "v1.35.9+k3s1"
  validation {
    condition     = can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+\\+k3s[0-9]+$", var.k3s_version))
    error_message = "Use a pinned stable K3s release version."
  }
}

variable "cert_manager_version" {
  type    = string
  default = "v1.21.3"
  validation {
    condition     = can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+$", var.cert_manager_version))
    error_message = "Use a pinned cert-manager release."
  }
}
