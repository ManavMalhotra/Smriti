[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
try {
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
        & uv venv .venv --python 3.11 *> $null
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -m venv .venv *> $null
    } else {
        & python -m venv .venv *> $null
    }
    if ($LASTEXITCODE -ne 0) { throw "Environment setup failed." }
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
        & uv pip install --python $Python -r $Requirements *> $null
        if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed." }
    } else {
        & $Python -m ensurepip --upgrade *> $null
        if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed." }
        & $Python -m pip install --upgrade pip *> $null
        if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed." }
        & $Python -m pip install -r $Requirements *> $null
        if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed." }
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
        & $Npm --prefix web ci *> $null
    } else {
        & $Npm --prefix web install *> $null
    }
    if ($LASTEXITCODE -ne 0) { throw "Frontend setup failed." }
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
    & $Npm --prefix web run build *> $null
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
}

$env:PYTHONUTF8 = "1"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
Write-Host ""
Write-Host "Smriti is starting at http://127.0.0.1:$Port/"
Write-Host "Press Ctrl+C to stop."
Write-Host ""
& $Python -m smriti.server --port $Port
if ($LASTEXITCODE -ne 0) { throw "Smriti stopped (exit code $LASTEXITCODE)." }
} catch {
    Write-Host $_.Exception.Message
    Write-Host "Logs: $Root\data\logs\smriti.jsonl"
    exit 1
}
