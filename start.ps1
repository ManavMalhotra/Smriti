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
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Python = $VenvPython
$Requirements = Join-Path $Root "requirements.txt"
$RequirementsMarker = Join-Path $Venv ".smriti-requirements.sha256"

function Get-Npm {
    $command = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $command = Get-Command npm -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Node.js and npm are required. Install Node 20.19+ or 22.12+."
}

function Invoke-Tool {
    param([scriptblock]$Script)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & $Script
    } finally {
        $ErrorActionPreference = $prev
    }
}

if (-not (Test-Path $Python)) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        Invoke-Tool { & uv venv .venv --python 3.11 *> $null }
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        Invoke-Tool { & py -3.11 -m venv .venv *> $null }
    } else {
        Invoke-Tool { & python -m venv .venv *> $null }
    }
    if ($LASTEXITCODE -ne 0) { throw "Environment setup failed." }
}

# Resolve and verify functional Python executable
if (Test-Path (Join-Path $Venv "pyvenv.cfg")) {
    $homeLine = Get-Content (Join-Path $Venv "pyvenv.cfg") | Where-Object { $_ -match '^home\s*=\s*(.+)$' }
    if ($homeLine -and $Matches[1]) {
        $baseHome = $Matches[1].Trim()
        $basePython = Join-Path $baseHome "python.exe"
        $venvWorks = $false
        try {
            $null = & $Python -c "import ssl, uvicorn" 2>$null
            if ($LASTEXITCODE -eq 0) { $venvWorks = $true }
        } catch {
            $venvWorks = $false
        }
        if (-not $venvWorks -and (Test-Path $basePython)) {
            $Python = $basePython
            $sitePackages = Join-Path $Venv "Lib\site-packages"
            $env:PYTHONPATH = if ($env:PYTHONPATH) { "$Root;$sitePackages;$($env:PYTHONPATH)" } else { "$Root;$sitePackages" }
        }
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
        Invoke-Tool { & uv pip install --quiet --python $VenvPython -r $Requirements *> $null }
        if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed." }
    } else {
        Invoke-Tool { & $Python -m ensurepip --upgrade *> $null }
        if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed." }
        Invoke-Tool { & $Python -m pip install --quiet --upgrade pip *> $null }
        if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed." }
        Invoke-Tool { & $Python -m pip install --quiet -r $Requirements *> $null }
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
        Invoke-Tool { & $Npm --prefix web ci *> $null }
    } else {
        Invoke-Tool { & $Npm --prefix web install *> $null }
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
    Invoke-Tool { & $Npm --prefix web run build *> $null }
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
# Ctrl+C exits with STATUS_CONTROL_C_EXIT (-1073741510 / 3221225786); that is a normal stop.
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1073741510 -and $LASTEXITCODE -ne 3221225786) {
    throw "Smriti stopped (exit code $LASTEXITCODE)."
}
} catch {
    Write-Host $_.Exception.Message
    Write-Host "Logs: $Root\data\logs\smriti.jsonl"
    exit 1
}
