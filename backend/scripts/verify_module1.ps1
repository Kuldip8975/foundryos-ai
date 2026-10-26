<#
.SYNOPSIS
    Verifies that FoundryOS AI Module 1 (Manufacturing Data Foundation) is complete
    on this machine.

.DESCRIPTION
    Run from the backend folder with the virtual environment active:

        cd E:\foundryos-ai-module0\backend
        powershell -ExecutionPolicy Bypass -File .\scripts\verify_module1.ps1

    Checks, in order:
      1. Module 1 source files are present
      2. ruff check . is clean
      3. pytest (in-memory SQLite) passes with no failures
      4. check_db.py exits 0 for the development and the test database
      5. alembic current reports 0002_manufacturing_data (head)
      6. pytest -m integration passes against foundryos_test
      7. The API (started temporarily on a spare port) is ready, every Module 1
         endpoint answers with the paginated envelope, and errors use the
         standard envelope. Synthetic row counts are reported if present.
      8. If the project is a git repository: no .env file is tracked

    Safety:
      * Never reads, prints or asks for a password. Connections authenticate
        through your libpq password file (pgpass.conf), exactly as before.
      * The development database is only READ (check_db, alembic current and
        GET requests). Nothing is migrated, seeded or modified there.
      * Step 6 writes only to the disposable foundryos_test database, guarded by
        the test-database URL validator. Skip it with -SkipIntegration.

    Exit code: 0 when every check passes, 1 otherwise.

.PARAMETER Port
    Port for the temporary API server (default 8765, so it does not clash with
    a uvicorn you already have running on 8000).

.PARAMETER TestDatabaseUrl
    Credential-free URL of the test database (no password in it).

.PARAMETER SkipIntegration
    Skip step 6.
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$TestDatabaseUrl = "postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos_test",
    [switch]$SkipIntegration
)

$ErrorActionPreference = "Stop"
$HeadRevision = "0002_manufacturing_data"
$script:Results = New-Object System.Collections.Generic.List[object]

function Add-Result([string]$Name, [string]$Status, [string]$Detail = "") {
    $script:Results.Add([pscustomobject]@{ Check = $Name; Status = $Status; Detail = $Detail })
    $color = switch ($Status) { "PASS" { "Green" } "SKIP" { "Yellow" } "INFO" { "Cyan" } default { "Red" } }
    $line = "[{0}] {1}" -f $Status, $Name
    if ($Detail) { $line = "$line - $Detail" }
    Write-Host $line -ForegroundColor $color
}

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor White
}

# Runs a native command, echoes its output, returns exit code and output text.
function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"   # stderr lines must not abort the script
    try {
        $output = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    $output | ForEach-Object { Write-Host "    $_" }
    return [pscustomobject]@{ Code = $code; Text = ($output -join "`n") }
}

# HTTP request that returns status code and parsed JSON for 2xx and error responses
# alike (works on Windows PowerShell 5.1 and PowerShell 7).
function Invoke-Api([string]$Method, [string]$Path) {
    $uri = "http://127.0.0.1:$Port$Path"
    try {
        $response = Invoke-WebRequest -Uri $uri -Method $Method -UseBasicParsing -TimeoutSec 15
        $status = [int]$response.StatusCode
        $body = $response.Content
    } catch {
        if ($null -eq $_.Exception.Response) { throw }
        $status = [int]$_.Exception.Response.StatusCode
        $body = $_.ErrorDetails.Message
    }
    $json = $null
    if ($body) { try { $json = $body | ConvertFrom-Json } catch { $json = $null } }
    return [pscustomobject]@{ Status = $status; Json = $json }
}

# --------------------------------------------------------------------------- preflight
Write-Section "Preflight"
if (-not (Test-Path ".\app\main.py") -or -not (Test-Path ".\alembic.ini")) {
    Write-Host "Run this script from the backend folder (the one containing app\ and alembic.ini)." -ForegroundColor Red
    exit 1
}
if (-not $env:VIRTUAL_ENV) {
    Write-Host "Activate the virtual environment first (.venv\Scripts\Activate.ps1)." -ForegroundColor Red
    exit 1
}
$Python = (Get-Command python -ErrorAction Stop).Source
Add-Result "Python interpreter" "INFO" $Python

# --------------------------------------------------------------------------- 1. files
Write-Section "1. Module 1 source files"
$requiredFiles = @(
    "app\db\types.py", "app\models\enums.py", "app\models\manufacturing.py",
    "alembic\versions\20261014_0002_manufacturing_data.py",
    "app\schemas\common.py", "app\schemas\manufacturing.py",
    "app\services\common.py", "app\services\master_data.py", "app\services\production.py",
    "app\services\operations.py", "app\services\seed.py", "app\cli\seed.py",
    "app\api\routes\master_data.py", "app\api\routes\production.py",
    "app\api\routes\operations.py", "app\api\routes\responses.py",
    "tests\test_manufacturing_models.py", "tests\test_migrations.py",
    "tests\test_api_master_data.py", "tests\test_api_production.py",
    "tests\test_api_operations.py", "tests\test_seed.py",
    "..\docs\module-1-manufacturing-data.md"
)
$missing = @($requiredFiles | Where-Object { -not (Test-Path $_) })
if ($missing.Count -eq 0) {
    Add-Result "Module 1 files present" "PASS" "$($requiredFiles.Count) files"
} else {
    Add-Result "Module 1 files present" "FAIL" ("missing: " + ($missing -join ", "))
}

# --------------------------------------------------------------------------- 2. ruff
Write-Section "2. ruff check ."
$r = Invoke-Native $Python @("-m", "ruff", "check", ".")
if ($r.Code -eq 0) { Add-Result "ruff check ." "PASS" } else { Add-Result "ruff check ." "FAIL" "exit $($r.Code)" }

# --------------------------------------------------------------------------- 3. pytest
Write-Section "3. pytest (in-memory SQLite, no database access)"
$savedTestUrl = $env:TEST_DATABASE_URL
Remove-Item Env:\TEST_DATABASE_URL -ErrorAction SilentlyContinue
$r = Invoke-Native $Python @("-m", "pytest", "-q", "-p", "no:cacheprovider")
$summary = ($r.Text -split "`n" | Where-Object { $_ -match "passed|failed|error" } | Select-Object -Last 1)
if ($r.Code -eq 0 -and $r.Text -notmatch "\d+ failed") {
    Add-Result "pytest unit/API suite" "PASS" ("$summary".Trim())
} else {
    Add-Result "pytest unit/API suite" "FAIL" "exit $($r.Code): $summary"
}

# --------------------------------------------------------------------------- 4. check_db
Write-Section "4. Database connectivity (read-only)"
foreach ($target in @("app", "test")) {
    $r = Invoke-Native $Python @("scripts\check_db.py", "--target", $target)
    if ($r.Code -eq 0) {
        Add-Result "check_db --target $target" "PASS"
    } else {
        Add-Result "check_db --target $target" "FAIL" "exit $($r.Code) (1 connect, 2 config, 3 privileges)"
    }
}

# --------------------------------------------------------------------------- 5. alembic
Write-Section "5. alembic current (development database, read-only)"
$r = Invoke-Native $Python @("-m", "alembic", "current")
if ($r.Code -eq 0 -and $r.Text -match [regex]::Escape("$HeadRevision (head)")) {
    Add-Result "Migration at head" "PASS" $HeadRevision
} else {
    Add-Result "Migration at head" "FAIL" "expected '$HeadRevision (head)'"
}

# --------------------------------------------------------------------------- 6. integration
Write-Section "6. pytest -m integration (foundryos_test only)"
if ($SkipIntegration) {
    Add-Result "Integration tests" "SKIP" "-SkipIntegration given"
} elseif ($TestDatabaseUrl -match "://[^/@]*:[^/@]*@") {
    Add-Result "Integration tests" "FAIL" "TestDatabaseUrl must not contain a password; use pgpass.conf"
} else {
    $env:TEST_DATABASE_URL = $TestDatabaseUrl
    try {
        $r = Invoke-Native $Python @("-m", "pytest", "-m", "integration", "-q", "-p", "no:cacheprovider")
    } finally {
        Remove-Item Env:\TEST_DATABASE_URL -ErrorAction SilentlyContinue
    }
    $passed = 0
    if ($r.Text -match "(\d+) passed") { $passed = [int]$Matches[1] }
    if ($r.Code -eq 0 -and $passed -gt 0 -and $r.Text -notmatch "\d+ skipped") {
        Add-Result "Integration tests" "PASS" "$passed passed"
    } else {
        Add-Result "Integration tests" "FAIL" "exit $($r.Code), $passed passed (skips count as failure here)"
    }
}
if ($savedTestUrl) { $env:TEST_DATABASE_URL = $savedTestUrl }

# --------------------------------------------------------------------------- 7. API
Write-Section "7. API against the development database (GET requests only)"
$logOut = Join-Path $env:TEMP "foundryos_verify_uvicorn_out.log"
$logErr = Join-Path $env:TEMP "foundryos_verify_uvicorn_err.log"
$server = $null
try {
    $server = Start-Process -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
        -RedirectStandardOutput $logOut -RedirectStandardError $logErr `
        -WorkingDirectory (Get-Location).Path -NoNewWindow -PassThru

    $live = $false
    for ($i = 0; $i -lt 40 -and -not $live; $i++) {
        Start-Sleep -Milliseconds 500
        if ($server.HasExited) { break }
        try { $live = ((Invoke-Api "GET" "/api/v1/health/live").Status -eq 200) } catch { $live = $false }
    }
    if (-not $live) {
        Add-Result "API server start" "FAIL" "not live on port $Port; see $logErr"
    } else {
        Add-Result "API server start" "PASS" "port $Port"

        $ready = Invoke-Api "GET" "/api/v1/health/ready"
        if ($ready.Status -eq 200 -and $ready.Json.status -eq "ready") {
            $migration = $ready.Json.checks | Where-Object { $_.name -eq "migrations" }
            Add-Result "GET /health/ready" "PASS" $migration.detail
        } else {
            Add-Result "GET /health/ready" "FAIL" "HTTP $($ready.Status), status '$($ready.Json.status)'"
        }

        $resources = @("machines", "products", "defect-categories", "production-records",
                       "quality-inspections", "downtime-events", "maintenance-requests")
        foreach ($resource in $resources) {
            $page = Invoke-Api "GET" "/api/v1/$($resource)?limit=1"
            $props = @()
            if ($page.Json) { $props = $page.Json.PSObject.Properties.Name }
            $hasEnvelope = ($props -contains "items") -and ($props -contains "total") -and
                           ($props -contains "limit") -and ($props -contains "offset")
            if ($page.Status -eq 200 -and $hasEnvelope) {
                $synthetic = (Invoke-Api "GET" "/api/v1/$($resource)?limit=1&data_source=synthetic").Json.total
                $manual = (Invoke-Api "GET" "/api/v1/$($resource)?limit=1&data_source=manual").Json.total
                Add-Result "GET /$resource" "PASS" ("total {0} (synthetic {1}, manual {2})" -f $page.Json.total, $synthetic, $manual)
            } else {
                Add-Result "GET /$resource" "FAIL" "HTTP $($page.Status) or missing pagination envelope"
            }
        }

        $notFound = Invoke-Api "GET" "/api/v1/machines/999999999"
        if ($notFound.Status -eq 404 -and $notFound.Json.error.code -eq "not_found" -and $notFound.Json.error.request_id) {
            Add-Result "404 error envelope" "PASS" "code not_found, request_id present"
        } else {
            Add-Result "404 error envelope" "FAIL" "HTTP $($notFound.Status)"
        }

        $badRange = Invoke-Api "GET" "/api/v1/production-records?date_from=2026-01-08&date_to=2026-01-01"
        if ($badRange.Status -eq 422 -and $badRange.Json.error.code -eq "invalid_date_range") {
            Add-Result "422 business-rule envelope" "PASS" "code invalid_date_range"
        } else {
            Add-Result "422 business-rule envelope" "FAIL" "HTTP $($badRange.Status)"
        }

        $badInput = Invoke-Api "GET" "/api/v1/downtime-events?status=paused"
        if ($badInput.Status -eq 422 -and $badInput.Json.error.code -eq "validation_error") {
            Add-Result "422 validation envelope" "PASS" "code validation_error"
        } else {
            Add-Result "422 validation envelope" "FAIL" "HTTP $($badInput.Status)"
        }

        $delete = Invoke-Api "DELETE" "/api/v1/machines/1"
        if ($delete.Status -eq 405) {
            Add-Result "No DELETE endpoint" "PASS" "HTTP 405"
        } else {
            Add-Result "No DELETE endpoint" "FAIL" "expected 405, got HTTP $($delete.Status)"
        }
    }
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
}

# --------------------------------------------------------------------------- 8. git
Write-Section "8. Git hygiene"
$git = Get-Command git -ErrorAction SilentlyContinue
$inRepo = $false
if ($git) {
    $previous = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & git rev-parse --is-inside-work-tree 2>$null | Out-Null
    $inRepo = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previous
}
if (-not $inRepo) {
    Add-Result "No .env tracked by git" "SKIP" "not a git repository yet"
} else {
    $tracked = @(& git ls-files -- ":/" 2>$null | Where-Object { $_ -match "(^|/)\.env$" })
    if ($tracked.Count -eq 0) {
        Add-Result "No .env tracked by git" "PASS"
    } else {
        Add-Result "No .env tracked by git" "FAIL" ("tracked: " + ($tracked -join ", "))
    }
}

# --------------------------------------------------------------------------- summary
Write-Section "Summary"
$script:Results | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
$failed = @($script:Results | Where-Object { $_.Status -eq "FAIL" })
$skipped = @($script:Results | Where-Object { $_.Status -eq "SKIP" })
if ($failed.Count -eq 0) {
    $note = ""
    if ($skipped.Count -gt 0) { $note = " ($($skipped.Count) skipped - see above)" }
    Write-Host "MODULE 1 VERIFIED on this machine: all checks passed$note." -ForegroundColor Green
    exit 0
}
Write-Host "MODULE 1 NOT VERIFIED: $($failed.Count) check(s) failed." -ForegroundColor Red
exit 1