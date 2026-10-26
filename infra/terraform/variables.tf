variable "aws_region" {
  description = "AWS region for the server."
  type        = string
  default     = "ap-south-1" # Mumbai
}

variable "project_name" {
  description = "Name used for the instance, security group and tags."
  type        = string
  default     = "foundryos"
}

variable "instance_type" {
  description = "EC2 size. t3.micro is free-tier eligible; t3.small builds faster."
  type        = string
  default     = "t3.micro"
}

variable "root_volume_gb" {
  description = "Disk size in GB (database, Docker images, backups)."
  type        = number
  default     = 20

  validation {
    condition     = var.root_volume_gb >= 12 && var.root_volume_gb <= 100
    error_message = "Use between 12 and 100 GB."
  }
}

variable "ssh_public_key_path" {
  description = "Path to YOUR public SSH key (.pub). The private key never leaves your computer."
  type        = string
  default     = "~/.ssh/foundryos-key.pub"
}

variable "allowed_ssh_cidr" {
  description = "Only this address may use SSH, e.g. \"203.0.113.7/32\" (your public IP + /32)."
  type        = string

  validation {
    condition     = can(cidrhost(var.allowed_ssh_cidr, 0)) && var.allowed_ssh_cidr != "0.0.0.0/0"
    error_message = "Give your own IP as a CIDR such as 203.0.113.7/32 (opening SSH to 0.0.0.0/0 is not allowed)."
  }
}

variable "repo_url" {
  description = "Public git URL cloned to /home/ubuntu/foundryos-ai on first boot. Empty = do not clone."
  type        = string
  default     = "https://github.com/Kuldip8975/foundryos-ai.git"
}