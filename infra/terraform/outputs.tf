output "api_url" {
  description = "HTTPS API address for the web client (VITE_API_BASE_URL)."
  value       = "${trimsuffix(aws_apigatewayv2_api.api.api_endpoint, "/")}/api/v1"
}

output "api_domain" {
  description = "Pass to deploy\\deploy-pages.ps1 -ApiDomain"
  value       = replace(aws_apigatewayv2_api.api.api_endpoint, "https://", "")
}

output "public_ip" {
  description = "Server address (SSH)."
  value       = aws_eip.public.public_ip
}

output "ssh_command" {
  description = "Connect from Windows PowerShell."
  value       = "ssh -i $HOME\\.ssh\\foundryos-key ubuntu@${aws_eip.public.public_ip}"
}

output "origin_secret" {
  description = "Put on the server as ORIGIN_SECRET in deploy/.env (terraform output -raw origin_secret)."
  value       = random_password.origin_secret.result
  sensitive   = true
}
