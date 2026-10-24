[CmdletBinding()]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Requirements = Join-Path $Root "requirements.txt"
$RequirementsMarker = Join-Path $Venv ".smriti-requirements.sha256"

function Get-Npm {
    $command = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $command = Get-Command npm -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Node.js and npm are required. Install Node 20.19+ or 22.12+."
}

if (-not (Test-Path $Python)) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        & uv venv .venv --python 3.11
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -m venv .venv
    } else {
        & python -m venv .venv
    }
}

if (-not (Test-Path $Python)) {
    throw "Python 3.11 is required. Install it, then run start.ps1 again."
}

$wanted = (Get-FileHash $Requirements -Algorithm SHA256).Hash
$installed = if (Test-Path $RequirementsMarker) {
    (Get-Content $RequirementsMarker -Raw).Trim()
} else {
    ""
}
if ($wanted -ne $installed) {
    Write-Host "Installing Python dependencies..."
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        & uv pip install --python $Python -r $Requirements
    } else {
        & $Python -m ensurepip --upgrade | Out-Null
        & $Python -m pip install --upgrade pip
        & $Python -m pip install -r $Requirements
    }
    Set-Content -Path $RequirementsMarker -Value $wanted -NoNewline
}

$Npm = Get-Npm
$NodeModules = Join-Path $Root "web\node_modules"
$PackageLock = Join-Path $Root "web\package-lock.json"
$Dist = Join-Path $Root "web\dist\index.html"

$needsInstall = -not (Test-Path $NodeModules)
if (-not $needsInstall -and (Test-Path $PackageLock)) {
    $installedLock = Join-Path $NodeModules ".package-lock.json"
    $needsInstall = -not (Test-Path $installedLock) -or
        (Get-Item $PackageLock).LastWriteTimeUtc -gt (Get-Item $installedLock).LastWriteTimeUtc
}
if ($needsInstall) {
    Write-Host "Installing frontend dependencies..."
    if (Test-Path $PackageLock) {
        & $Npm --prefix web ci
    } else {
        & $Npm --prefix web install
    }
}

$needsBuild = -not (Test-Path $Dist)
if (-not $needsBuild) {
    $distTime = (Get-Item $Dist).LastWriteTimeUtc
    $inputs = @(
        (Join-Path $Root "web\src"),
        (Join-Path $Root "web\index.html"),
        (Join-Path $Root "web\vite.config.js"),
        (Join-Path $Root "web\package.json")
    )
    $newer = Get-ChildItem $inputs -Recurse -File |
        Where-Object { $_.LastWriteTimeUtc -gt $distTime } |
        Select-Object -First 1
    if ($newer) { $needsBuild = $true }
}
if ($needsBuild) {
    Write-Host "Building the web app..."
    & $Npm --prefix web run build
}

$env:PYTHONUTF8 = "1"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
Write-Host ""
Write-Host "Smriti is starting at http://127.0.0.1:$Port/"
Write-Host "Press Ctrl+C to stop."
Write-Host ""
& $Python -m uvicorn smriti.main:app --host 127.0.0.1 --port $Port
