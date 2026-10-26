# Deploying FoundryOS AI on AWS (one EC2 server)

This guide puts the whole system on **one EC2 instance**:

```
Internet ──HTTPS──▶ Caddy (web client + automatic certificate)
                       ├── /        → React web client
                       └── /api/*   → FastAPI backend ──▶ PostgreSQL
                                     (internal Docker network only)
```

- **One public address:** a free DuckDNS subdomain, for example `https://foundryos.duckdns.org`.
- **HTTPS:** automatic via Let's Encrypt, renewed by Caddy.
- **Database:** PostgreSQL in a Docker volume on the same server, with a daily backup script.
- **Demo mode (optional):** three shared demo accounts on the sign-in page and synthetic data, so recruiters can try the app.

## Cost

- **Free tier (new AWS account, first 12 months):**
  - t3.micro (or t2.micro) instance;
  - 30 GB of EBS storage;
  - 750 hours of public IPv4.
- **After the free tier:** roughly **US$10–12 per month** in Mumbai (ap-south-1) for a t3.micro, 20 GB of storage and one Elastic IP. A t3.small (2 GB RAM, faster builds) is about US$20 per month. Check current prices in the AWS console.
- **Set a budget alert:** in the console, open **Billing → Budgets** and create a US$5 budget.

> **Web client on Cloudflare Pages instead (no domain needed)?** Follow [`deployment-cloudflare-pages.md`](deployment-cloudflare-pages.md).
>
> **Prefer Terraform?** [`deployment-terraform.md`](deployment-terraform.md) does steps 1, 2, 4 and 5 for you. Then come back to step 3, and to step 6 onwards.

## 1. Launch the EC2 instance

In the AWS console (region **Asia Pacific (Mumbai) ap-south-1**), go to **EC2 → Launch instance**:

| Setting | Value |
|---|---|
| Name | `foundryos-prod` |
| Image | **Ubuntu Server 24.04 LTS** (64-bit x86) |
| Instance type | `t3.micro` (free tier) or `t3.small` |
| Key pair | Create a new key pair (`foundryos-key`, `.pem`) and keep the file safe |
| Network → Security group | Create a new group with these inbound rules: **SSH 22 from "My IP"**, **HTTP 80 from Anywhere**, **HTTPS 443 from Anywhere** |
| Storage | 20 GB gp3 |

Then click **Launch instance**.

## 2. Give it a fixed address (Elastic IP)

1. Go to **EC2 → Elastic IPs → Allocate Elastic IP address → Allocate**.
2. Select the new IP, choose **Actions → Associate**, and pick the `foundryos-prod` instance.
3. Note the IP address, for example `13.200.10.20`.

## 3. Get a free domain name (DuckDNS)

1. Go to <https://www.duckdns.org> and sign in, for example with GitHub.
2. Add a subdomain, for example `foundryos`.
3. In **current ip**, enter the Elastic IP and click **update ip**.
4. Wait a minute. `ping foundryos.duckdns.org` should then answer from your Elastic IP.

## 4. Connect to the server

From Windows PowerShell, in the folder where the `.pem` file is:

```powershell
ssh -i .\foundryos-key.pem ubuntu@foundryos.duckdns.org
```

If Windows complains about key permissions:
```powershell
icacls .\foundryos-key.pem /inheritance:r /grant:r "$($env:USERNAME):R"
```

## 5. Prepare the server (once)

```bash
git clone https://github.com/Kuldip8975/foundryos-ai.git
cd foundryos-ai
bash deploy/setup-ec2.sh
exit            # log out and back in so Docker works without sudo
```

The script installs Docker, adds 2 GB of swap (needed for building on small instances), turns on the firewall and enables automatic security updates.

## 6. Configure

```bash
ssh -i .\foundryos-key.pem ubuntu@foundryos.duckdns.org
cd foundryos-ai/deploy
cp .env.production.example .env
openssl rand -hex 24          # copy this as POSTGRES_PASSWORD
nano .env
```

Fill in the following, then save with **Ctrl+O, Enter, Ctrl+X**:

| Setting | Example |
|---|---|
| `COMPOSE_FILE` | `docker-compose.prod.yml` (this single-server setup) |
| `SITE_DOMAIN` | `foundryos.duckdns.org` (uncomment the line) |
| `ACME_EMAIL` | your email, for certificate notices (uncomment the line) |
| `FRONTEND_ORIGIN` | only when the web client is on Cloudflare Pages, e.g. `https://foundryos.pages.dev` (see `deployment-cloudflare-pages.md`) |
| `POSTGRES_PASSWORD` | the `openssl` output |
| `DEMO_MODE` | `true` for a public demo |
| `PUBLIC_DEMO_PASSWORD` | a **new** password shown publicly on the sign-in page, for example `Try-Foundry-2026`. Never reuse a real password. |
| AI settings | leave `false` (see "AI on a public demo" below) |

`deploy/.env` exists only on the server. It is ignored by git and must never be committed.

## 7. Start

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

The first build takes 5–15 minutes on a t3.micro.

```bash
docker compose -f docker-compose.prod.yml ps                 # db, backend, web: running; migrate: exited (0)
docker compose -f docker-compose.prod.yml logs -f web        # watch Caddy obtain the certificate
curl https://foundryos.duckdns.org/api/v1/health/ready       # {"status":"ready",...}
```

## 8. Data and accounts

**Synthetic demo data.** This is for the public demo only. The seed refuses to run in production unless you deliberately run it with `ENVIRONMENT=development`:

```bash
docker compose -f docker-compose.prod.yml run --rm -e ENVIRONMENT=development backend \
  python -m app.cli.seed --apply
```

**Your private admin account.** Do not share it. Choose a strong password:

```bash
docker compose -f docker-compose.prod.yml run --rm backend \
  python -m app.cli.create_admin admin --name "Plant Admin"
```

**Demo accounts.** This creates `demo.operator`, `demo.supervisor` and `demo.manager` with `PUBLIC_DEMO_PASSWORD`:

```bash
docker compose -f docker-compose.prod.yml run --rm backend python -m app.cli.demo_accounts
```

Open `https://foundryos.duckdns.org`. The sign-in page shows **Try the live demo** with one button per role. With `DEMO_MODE=true`, demo accounts cannot change the shared password. No admin account is ever published.

## 9. Backups and daily demo reset

```bash
crontab -e
```

Add these two lines, replacing `ubuntu` if your user is different:

```
30 2 * * * bash /home/ubuntu/foundryos-ai/deploy/backup-db.sh >> /home/ubuntu/backup.log 2>&1
45 2 * * * cd /home/ubuntu/foundryos-ai/deploy && docker compose -f docker-compose.prod.yml run --rm backend python -m app.cli.demo_accounts >> /home/ubuntu/demo-reset.log 2>&1
```

- **Backups** are written to `deploy/backups/`, and the last 7 days are kept. Copy them off the server now and then, for example to S3.
- **Restore a backup:**

  ```bash
  docker compose -f docker-compose.prod.yml exec -T db pg_restore -U foundryos -d foundryos --clean < backups/<file>.dump
  ```

## 10. Updating after new code is pushed

```bash
cd ~/foundryos-ai
git pull
cd deploy
bash backup-db.sh
docker compose -f docker-compose.prod.yml up -d --build      # runs new migrations automatically
```

## AI on a public demo

AI is off by default. If you set `AI_REPORTS_ENABLED=true` and `AI_WORKFLOW_ENABLED=true` and add a `GEMINI_API_KEY`:

- **Cost:** every visitor's question uses your Gemini quota, and can cost money on a paid key. Use a free-tier key with a low quota, or enable AI only while you are presenting.
- **What is sent:** only aggregated, synthetic figures (see `docs/module-3-shift-reports.md` and `docs/module-4-workflow-agent.md`).

After changing `.env`, run `docker compose -f docker-compose.prod.yml up -d` again.

## Security checklist

- [ ] The security group allows SSH (22) **only from your IP**, and 80/443 from anywhere.
- [ ] `deploy/.env` is filled in on the server only, and `POSTGRES_PASSWORD` is random.
- [ ] The admin password is private and strong. The demo password is new and used nowhere else.
- [ ] `https://` works, and `http://` redirects to it (Caddy does this automatically).
- [ ] `ENABLE_API_DOCS` stays `false` in production (it is set in the compose file).
- [ ] The daily backup cron is installed and backups are copied off the server.
- [ ] An AWS budget alert is set.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The browser shows a certificate error, or the Caddy log says "challenge failed" | DuckDNS must point to the Elastic IP, and ports 80/443 must be open in the security group. Restart with `docker compose -f docker-compose.prod.yml restart web`. |
| A build fails with "killed" or out of memory | Check that swap is on (`swapon --show`). Use a t3.small, or build while nothing else is running. |
| `migrate` exited with an error | `docker compose -f docker-compose.prod.yml logs migrate`. Usually `POSTGRES_*` values in `.env` changed after the database was created. |
| Sign-in says "Too many sign-in attempts" | Wait 5 minutes. Rate limits are per visitor, because the proxy passes the real client address. |
| The site still shows the old version after an update | Rebuild with `up -d --build`, then hard-refresh the browser (Ctrl+F5). |
