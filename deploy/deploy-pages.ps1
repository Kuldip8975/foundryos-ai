# Builds the web client and publishes it to Cloudflare Pages (run on Windows).
#
#   powershell -ExecutionPolicy Bypass -File .\deploy\deploy-pages.ps1 -ApiDomain foundryos-api.duckdns.org
#
# The first run opens the browser once to sign in to Cloudflare (npx wrangler login).
# The demo password is asked for (it is public on the sign-in page anyway, but it
# is not stored in this script). Leave it empty for a private deployment.
param(
  [Parameter(Mandatory = $true)][string]$ApiDomain,
  [string]$ProjectName = 'foundryos'
)
# Native tools report failure through $LASTEXITCODE (checked after each step).
$ErrorActionPreference = 'Continue'
$frontend = Join-Path (Split-Path $PSScriptRoot) 'frontend'
Set-Location $frontend

$demo = Read-Host 'PUBLIC_DEMO_PASSWORD (same as deploy/.env on the server; Enter = none)'

# Process-level variables win over frontend/.env files and vanish when this script ends.
$env:VITE_API_BASE_URL = "https://$ApiDomain/api/v1"
$env:VITE_DEMO_PASSWORD = $demo

Write-Host "==> Building for API https://$ApiDomain"
if (Test-Path package-lock.json) { npm ci } else { npm install }
if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
npm run build
if ($LASTEXITCODE -ne 0) { throw 'build failed' }
node scripts/pages-headers.mjs
if ($LASTEXITCODE -ne 0) { throw '_headers failed' }

Write-Host "==> Publishing to Cloudflare Pages project '$ProjectName'"
npx --yes wrangler@4 pages project list *> $null
if ($LASTEXITCODE -ne 0) { npx --yes wrangler@4 login }
# Creating fails harmlessly when the project already exists.
npx --yes wrangler@4 pages project create $ProjectName --production-branch main *> $null
npx --yes wrangler@4 pages deploy dist --project-name $ProjectName --branch main --commit-dirty=true
if ($LASTEXITCODE -ne 0) { throw 'wrangler deploy failed' }
Write-Host 'Done. The production URL is shown above (https://<project>.pages.dev).'
