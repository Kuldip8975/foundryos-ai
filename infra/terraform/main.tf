# FoundryOS AI on AWS: API + database on one EC2 server, HTTPS through API Gateway.
# The web client is published separately to Cloudflare Pages.
# (see docs/deployment-cloudflare-pages.md)
#
# Terraform creates: SSH key pair, security group, Ubuntu 24.04 instance with
# Docker prepared on first boot, a fixed public IP (Elastic IP), and an
# HTTP API Gateway (free HTTPS address) that forwards to the server.
# The application itself is started with Docker Compose on the server.

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_key_pair" "deploy" {
  key_name   = "${var.project_name}-key"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_security_group" "web" {
  name        = "${var.project_name}-web"
  description = "FoundryOS AI: API Gateway to Caddy on 80, SSH only from the admin address"

  ingress {
    description = "SSH (admin only)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  # API Gateway has no fixed addresses, so port 80 is open; Caddy answers only
  # requests that carry the API Gateway secret header (403 otherwise).
  ingress {
    description = "HTTP from API Gateway (secret header checked by Caddy)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Outbound (updates, Docker images, certificates)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "server" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.deploy.key_name
  vpc_security_group_ids = [aws_security_group.web.id]

  # Runs once on first boot: the same preparation as deploy/setup-ec2.sh.
  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    setup_script = file("${path.module}/../../deploy/setup-ec2.sh")
    repo_url     = var.repo_url
  })

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  tags = {
    Name = "${var.project_name}-prod"
  }

  lifecycle {
    # A newer Ubuntu image or an edited boot script must NOT replace the
    # running server (that would delete the database on its disk).
    ignore_changes = [ami, user_data]
  }
}

resource "aws_eip" "public" {
  domain   = "vpc"
  instance = aws_instance.server.id

  tags = {
    Name = "${var.project_name}-ip"
  }
}

# --- HTTPS for the API: AWS API Gateway (HTTP API) -> server port 80 ---

# Shared secret that proves a request came through API Gateway.
# Put it on the server as ORIGIN_SECRET (terraform output -raw origin_secret).
resource "random_password" "origin_secret" {
  length  = 48
  special = false
}

resource "aws_apigatewayv2_api" "api" {
  name          = "${var.project_name}-api"
  protocol_type = "HTTP"
  description   = "FoundryOS AI API (HTTPS) -> EC2"
  # No CORS settings here on purpose: preflight requests go to FastAPI,
  # which allows only FRONTEND_ORIGIN.
}

resource "aws_apigatewayv2_integration" "server" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  integration_uri        = "http://${aws_eip.public.public_dns}/{proxy}"
  payload_format_version = "1.0"
  timeout_milliseconds   = 30000

  request_parameters = {
    "overwrite:header.X-Origin-Secret" = random_password.origin_secret.result
    "overwrite:header.X-Client-IP"     = "$context.identity.sourceIp"
  }
}

resource "aws_apigatewayv2_route" "all" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.server.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  # Caps traffic (and cost) if the public demo is hammered.
  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 25
  }
}
