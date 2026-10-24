mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-southeast-1a"] }
  }
  mock_data "aws_ami" {
    defaults = { id = "ami-0123456789abcdef0" }
  }
}

variables {
  aws_region         = "ap-southeast-1"
  ami_id             = "ami-0123456789abcdef0"
  domain             = "gateway.harbor-demo.org"
  acme_email         = "ops@harbor-demo.org"
  gateway_image      = "ghcr.io/golden-shao/harbor/gateway@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  release_commit     = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  monthly_budget_usd = 50
}

run "public_entrypoint_and_instance_boundary" {
  command = plan
  assert {
    condition     = alltrue([for rule in aws_security_group.web.ingress : contains([80, 443], rule.from_port) && rule.from_port == rule.to_port]) && length(aws_security_group.web.ingress) == 2
    error_message = "Only HTTP/HTTPS may be exposed; never SSH, Redis, NodePort or Kubernetes API."
  }
  assert {
    condition     = aws_instance.gateway.metadata_options[0].http_tokens == "required" && aws_instance.gateway.metadata_options[0].http_put_response_hop_limit == 1 && aws_instance.gateway.root_block_device[0].encrypted && !aws_instance.gateway.root_block_device[0].delete_on_termination && aws_instance.gateway.ami == var.ami_id
    error_message = "Require IMDSv2, keep instance credentials away from Pods, and encrypt disk."
  }
  assert {
    condition     = strcontains(aws_instance.gateway.user_data, "scripts/cloud_credentials.py") && !strcontains(aws_instance.gateway.user_data, "ADMIN_TOKEN=") && !strcontains(aws_instance.gateway.user_data, "UPSTREAM_API_KEY=")
    error_message = "Generate instance credentials on the VM; do not embed secrets into Terraform/cloud-init."
  }
}

run "reject_mutable_image" {
  command = plan
  variables {
    gateway_image = "ghcr.io/example/gateway:latest"
  }
  expect_failures = [var.gateway_image]
}

run "require_explicit_budget" {
  command = plan
  variables {
    monthly_budget_usd = 0
  }
  expect_failures = [var.monthly_budget_usd]
}

run "reject_example_domain_before_creating_resources" {
  command = plan
  variables {
    domain = "gateway.example.com"
  }
  expect_failures = [var.domain]
}
