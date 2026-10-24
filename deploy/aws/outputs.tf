output "public_ip" {
  value = aws_eip.gateway.public_ip
}
output "website_url" {
  value       = "https://${var.domain}"
  description = "Intended URL; requires DNS and successful certificate issuance, not proof of deployment."
}
output "instance_id" {
  value = aws_instance.gateway.id
}
