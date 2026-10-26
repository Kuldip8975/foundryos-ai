# Creating the AWS server with Terraform

> The Terraform configuration also creates an **API Gateway** (HTTPS address for the API) for the Cloudflare Pages setup. The complete flow is in [`deployment-cloudflare-pages.md`](deployment-cloudflare-pages.md); this page explains the Terraform part.

`infra/terraform/` creates, in one command, what steps 1–5 of [`deployment-aws.md`](deployment-aws.md) set up by hand:

| Resource | Purpose |
|---|---|
| `aws_key_pair` | Your **public** SSH key (the private key stays on your computer) |
| `aws_security_group` | 80 open (API Gateway; Caddy answers only requests with the secret header); 22 only from your IP |
| `aws_instance` | Ubuntu 24.04, t3.micro, 20 GB encrypted gp3, IMDSv2 only |
| `aws_eip` | Fixed public IP |
| `aws_apigatewayv2_*` | HTTPS API address forwarding to the server (needs **AmazonAPIGatewayAdministrator** on the IAM user) |
| `random_password` | `origin_secret`, which proves a request came through API Gateway |

On first boot the server runs `deploy/setup-ec2.sh` (Docker, swap, firewall, automatic updates) and clones the repository to `/home/ubuntu/foundryos-ai`.

Terraform does **not** handle the following:

- the DuckDNS name;
- `deploy/.env` (secrets never go into Terraform);
- starting the app.

Those stay as in `deployment-aws.md`, steps 3 and 6 onwards.

## 1. One-time setup on Windows

```powershell
winget install Hashicorp.Terraform
winget install Amazon.AWSCLI
# Close and reopen PowerShell, then:
terraform -version
```

**AWS access key**

1. In the AWS console, go to **IAM → Users → Create user**, for example `terraform-admin`.
2. Attach the policy **AmazonEC2FullAccess**.
3. Open the user and go to **Security credentials → Create access key → Command Line Interface**.
4. Never create access keys for the root account.
5. Configure the CLI with the new key:

```powershell
aws configure            # access key, secret key, region: ap-south-1, output: json
aws sts get-caller-identity
```

The keys are saved in `%USERPROFILE%\.aws\credentials`, outside the project. Never put them in the repository.

**SSH key** (press Enter twice for no passphrase, or set one):

```powershell
ssh-keygen -t ed25519 -f $HOME\.ssh\foundryos-key
```

## 2. Configure

```powershell
cd E:\foundryos-ai-module0\infra\terraform
copy terraform.tfvars.example terraform.tfvars
(Invoke-RestMethod https://checkip.amazonaws.com).Trim()   # your public IP
notepad terraform.tfvars                                   # allowed_ssh_cidr = "<that IP>/32"
```

`terraform.tfvars` and the `*.tfstate` files are git-ignored. Do not commit them.

## 3. Create the server

```powershell
terraform init
terraform plan        # review: 8 resources to add
terraform apply       # type: yes
```

The output shows `public_ip` and `ssh_command`.

## 4. Continue the normal guide

1. Put `public_ip` in DuckDNS (`deployment-aws.md`, step 3).
2. Connect and wait for the first-boot preparation to finish (2–5 minutes):

   ```powershell
   ssh -i $HOME\.ssh\foundryos-key ubuntu@<public_ip>
   ```
   ```bash
   cloud-init status --wait          # status: done
   docker --version
   ls ~/foundryos-ai
   ```
3. Continue with `deployment-aws.md` **step 6 (Configure)**. Steps 1, 2, 4 and 5 are already done.

If the repository is private, the clone is skipped. Clone it yourself with a GitHub token, or set `repo_url = ""` and copy the code another way.

## Your IP changed (SSH times out)

Home IPs change. Update `allowed_ssh_cidr` in `terraform.tfvars`, then run `terraform apply`. Only the security-group rule changes.

## Warnings

- **`terraform destroy` deletes the server, its disk and the database.** Take a backup first and copy it off the server.
- Changing `instance_type` stops and restarts the server. The data stays.
- The configuration ignores newer Ubuntu images and edits to the boot script, so a later `apply` never replaces the running server.
- The state file (`terraform.tfstate`) is the only record Terraform has of what it created. Keep it, and do not commit it. For a team, move it to an S3 backend.
