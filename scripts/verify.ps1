[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipEval
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment not found at $Python. Run .\start.ps1 once to create it."
}

function Invoke-Checked {
    param(
        [string]$Label,
        [scriptblock]$Command
    )
    Write-Host ""
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

Push-Location $Root
try {
    Invoke-Checked "Backend unit tests" { & $Python -m pytest -m unit }
    Invoke-Checked "Backend integration tests" { & $Python -m pytest -m integration }
    Invoke-Checked "Backend system tests" { & $Python -m pytest -m system }

    if (-not $SkipFrontend) {
        $Npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
        if (-not $Npm) {
            $Npm = (Get-Command npm -ErrorAction SilentlyContinue).Source
        }
        if (-not $Npm) {
            throw "npm was not found. Install Node 20.19+ or 22.12+."
        }

        Invoke-Checked "Frontend unit tests" { & $Npm --prefix web run test:unit }
        Invoke-Checked "Frontend integration tests" { & $Npm --prefix web run test:integration }
        Invoke-Checked "Frontend system tests" { & $Npm --prefix web run test:system }
        Invoke-Checked "Frontend full suite (catches unclassified test files)" {
            & $Npm --prefix web run test
        }
        Invoke-Checked "Frontend production build" { & $Npm --prefix web run build }
    }

    if (-not $SkipEval) {
        Invoke-Checked "Offline evaluation determinism smoke" {
            & $Python eval\run_eval.py --verify-determinism
        }
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "All verification checks passed." -ForegroundColor Green
