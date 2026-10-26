# FoundryOS AI - verify Modules 0-5 (backend + frontend).
#
# Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\verify_all.ps1
#
# Read-only for your data: it does NOT run migrations, change the database or
# edit any project file. (Tests use a temporary in-memory database; the build
# rewrites frontend\dist as usual.) Secrets are never printed.

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$results = New-Object System.Collections.Generic.List[object]

function Add-Result([string]$check, [string]$result, [string]$detail) {
    $results.Add([pscustomobject]@{ Check = $check; Result = $result; Detail = $detail })
    $color = switch ($result) { 'PASS' { 'Green' } 'FAIL' { 'Red' } default { 'Yellow' } }
    Write-Host ("[{0}] {1} {2}" -f $result, $check, $detail) -ForegroundColor $color
}

Write-Host "`nFoundryOS AI - verifying Modules 0-5 in $root`n" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1. key files
$required = @(
    'backend\app\main.py', 'backend\app\core\config.py', 'backend\app\core\security.py',
    'backend\app\models\manufacturing.py', 'backend\app\models\reports.py', 'backend\app\models\workflow.py',
    'backend\app\schemas\workflow.py', 'backend\app\services\analytics.py',
    'backend\app\services\shift_reports.py', 'backend\app\services\ai_provider.py',
    'backend\app\services\workflow\__init__.py', 'backend\app\services\workflow\agent.py',
    'backend\app\services\workflow\approvals.py', 'backend\app\services\workflow\tools.py',
    'backend\app\api\routes\workflows.py', 'backend\app\cli\workflow_token.py',
    'backend\alembic\versions\20261014_0002_manufacturing_data.py',
    'backend\alembic\versions\20261014_0003_shift_reports.py',
    'backend\alembic\versions\20261015_0004_workflow_agent.py',
    'frontend\src\pages\DashboardPage.jsx', 'frontend\src\pages\ReportsPage.jsx',
    'frontend\src\pages\AssistantPage.jsx', 'frontend\src\components\assistant\ProposalPanel.jsx',
    'frontend\src\components\AppShell.jsx',
    'backend\app\models\auth.py', 'backend\app\core\passwords.py', 'backend\app\core\permissions.py',
    'backend\app\api\auth.py', 'backend\app\api\scope.py', 'backend\app\api\routes\auth.py',
    'backend\app\api\routes\admin.py', 'backend\app\services\auth\sessions.py',
    'backend\app\services\auth\users.py', 'backend\app\cli\create_admin.py',
    'backend\alembic\versions\20261015_0005_auth_rbac.py',
    'frontend\src\auth\AuthContext.jsx', 'frontend\src\auth\session.js',
    'frontend\src\pages\LoginPage.jsx', 'frontend\src\pages\AdminPage.jsx',
    'frontend\src\pages\MyWorkPage.jsx', 'frontend\src\pages\AccountPage.jsx',
    'docs\module-1-manufacturing-data.md', 'docs\module-2-dashboard.md',
    'docs\module-3-shift-reports.md', 'docs\module-4-workflow-agent.md',
    'docs\module-5-auth-rbac.md'
)
$missing = @($required | Where-Object { -not (Test-Path (Join-Path $root $_)) })
if ($missing.Count -eq 0) { Add-Result 'Key files (Modules 0-5)' 'PASS' "$($required.Count) files present" }
else { Add-Result 'Key files (Modules 0-5)' 'FAIL' ("missing: " + ($missing -join ', ')) }

# Files that are easy to mix up when copying
$checks = @(
    @{ File = 'backend\app\models\workflow.py';  Pattern = 'persistence' },
    @{ File = 'backend\app\schemas\workflow.py'; Pattern = 'Schemas' },
    @{ File = 'frontend\src\components\AppShell.jsx'; Pattern = 'useAuth' },
    @{ File = 'frontend\src\App.jsx'; Pattern = 'AuthProvider' },
    @{ File = 'backend\app\api\routes\production.py'; Pattern = 'ProductionRecorder' }
)
$wrong = @()
foreach ($c in $checks) {
    $path = Join-Path $root $c.File
    if ((Test-Path $path) -and -not (Select-String -Path $path -Pattern $c.Pattern -Quiet)) { $wrong += $c.File }
}
if ($wrong.Count -eq 0) { Add-Result 'Files in the right place' 'PASS' '' }
else { Add-Result 'Files in the right place' 'FAIL' ("wrong content: " + ($wrong -join ', ')) }

# ---------------------------------------------------------------- 2. secrets safety
Push-Location $root
$isRepo = $false
if (Get-Command git -ErrorAction SilentlyContinue) {
    git rev-parse --is-inside-work-tree 2>$null | Out-Null
    $isRepo = ($LASTEXITCODE -eq 0)
}
if (-not $isRepo) {
    Add-Result '.env is ignored by git' 'SKIP' 'git not set up yet (run this check again after git init)'
} else {
    git check-ignore -q .env 2>$null
    if ($LASTEXITCODE -eq 0) { Add-Result '.env is ignored by git' 'PASS' '' }
    else { Add-Result '.env is ignored by git' 'FAIL' 'add .env to .gitignore before committing' }
}
Pop-Location

# ---------------------------------------------------------------- 3. backend
$backend = Join-Path $root 'backend'
$py = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Add-Result 'Backend virtual environment' 'FAIL' 'backend\.venv not found'
} else {
    Push-Location $backend

    $null = & $py -m ruff check . 2>&1
    if ($LASTEXITCODE -eq 0) { Add-Result 'Backend: ruff' 'PASS' 'All checks passed' }
    else { Add-Result 'Backend: ruff' 'FAIL' 'run: ruff check .' }

    Write-Host "Running backend tests (about 3 minutes)..." -ForegroundColor Cyan
    $out = & $py -m pytest -q -p no:cacheprovider 2>&1 | Out-String
    $summary = (($out -split "`r?`n") | Where-Object { $_ -match '\d+ (passed|failed)' } | Select-Object -Last 1)
    if ($LASTEXITCODE -eq 0) { Add-Result 'Backend: pytest' 'PASS' ("$summary".Trim()) }
    else { Add-Result 'Backend: pytest' 'FAIL' ("$summary".Trim()) }

    $current = & $py -m alembic current 2>&1 | Out-String
    if ($current -match '0005_auth_rbac \(head\)') { Add-Result 'Database migrations' 'PASS' 'at 0005_auth_rbac (head)' }
    elseif ($current -match '0004_workflow_agent|0003_shift_reports|0002_manufacturing_data') {
        Add-Result 'Database migrations' 'FAIL' 'not at head: run alembic upgrade head'
    } else { Add-Result 'Database migrations' 'FAIL' 'could not read migration state (is PostgreSQL running?)' }

    $cfg = & $py -c "from app.core.config import get_settings; s=get_settings(); print(s.ai_configured, s.workflow_ai_configured, len(s.workflow_access_entries))" 2>&1 | Select-Object -Last 1
    $parts = "$cfg".Trim() -split ' '
    if ($parts.Count -eq 3) {
        $detail = "shift reports AI: $($parts[0]); workflow AI: $($parts[1]); legacy tokens: $($parts[2])"
        if ($parts[1] -ne 'True') { Add-Result 'Settings (.env)' 'WARN' "$detail (assistant needs AI_WORKFLOW_ENABLED=true and a Gemini key)" }
        elseif ([int]$parts[2] -gt 0) { Add-Result 'Settings (.env)' 'WARN' "$detail (accounts replace tokens: empty WORKFLOW_ACCESS_TOKENS when ready)" }
        else { Add-Result 'Settings (.env)' 'PASS' $detail }
    } else { Add-Result 'Settings (.env)' 'FAIL' 'settings could not be loaded - check .env' }

    # Accounts (Module 5): counts only; never prints names or hashes.
    $acc = & $py -c "from sqlalchemy import func, select; from sqlalchemy.orm import Session; from app.db.session import get_engine; from app.models.auth import User; db=Session(get_engine()); print(db.scalar(select(func.count(User.id)).where(User.role=='admin', User.is_active.is_(True))), db.scalar(select(func.count(User.id))))" 2>&1 | Select-Object -Last 1
    $accParts = "$acc".Trim() -split ' '
    if ($accParts.Count -eq 2 -and [int]$accParts[0] -gt 0) { Add-Result 'Accounts' 'PASS' "active admins: $($accParts[0]); accounts: $($accParts[1])" }
    elseif ($accParts.Count -eq 2) { Add-Result 'Accounts' 'WARN' 'no admin yet: run python -m app.cli.create_admin <username> --name "Your Name"' }
    else { Add-Result 'Accounts' 'SKIP' 'could not count accounts (migrations not applied yet?)' }

    Pop-Location
}

# ---------------------------------------------------------------- 4. frontend
$frontend = Join-Path $root 'frontend'
Push-Location $frontend
Write-Host "Running frontend tests (about 2 minutes)..." -ForegroundColor Cyan
$out = npm test 2>&1 | Out-String
$testLine = (($out -split "`r?`n") | Where-Object { $_ -match '^\s*Tests\s' } | Select-Object -Last 1)
if ($LASTEXITCODE -eq 0) { Add-Result 'Frontend: tests' 'PASS' ("$testLine".Trim()) }
else { Add-Result 'Frontend: tests' 'FAIL' ("$testLine".Trim()) }

$out = npm run build 2>&1 | Out-String
if ($LASTEXITCODE -eq 0) { Add-Result 'Frontend: production build' 'PASS' 'built' }
else { Add-Result 'Frontend: production build' 'FAIL' 'run: npm run build' }
Pop-Location

# ---------------------------------------------------------------- 5. running backend (optional)
try {
    $ready = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/health/ready' -TimeoutSec 5
    Add-Result 'Running backend: readiness' 'PASS' "status: $($ready.status)"
} catch {
    if ($_.Exception.Response) { Add-Result 'Running backend: readiness' 'FAIL' 'backend answered but is not ready (database or migrations)' }
    else { Add-Result 'Running backend: readiness' 'SKIP' 'backend not running (start uvicorn to include this check)' }
}

# ---------------------------------------------------------------- summary
Write-Host ""
$results | Format-Table -AutoSize -Wrap
$failed = @($results | Where-Object { $_.Result -eq 'FAIL' }).Count
if ($failed -eq 0) { Write-Host "ALL CHECKS PASSED - Modules 0-5 verified." -ForegroundColor Green }
else { Write-Host "$failed check(s) FAILED - see the table above." -ForegroundColor Red }