param(
    [switch]$Detach,
    [switch]$SkipBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateDir = Join-Path $Root ".app"
$VenvDir = Join-Path $Root ".venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$WebDir = Join-Path $Root "web"
$NextEntry = Join-Path $WebDir "node_modules\next\dist\bin\next"
$PidFile = Join-Path $StateDir "pids.json"

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

$NodeMajor = [int]((node --version).TrimStart("v").Split(".")[0])
if ($NodeMajor -eq 21 -or $NodeMajor -lt 20) {
    Write-Warning "Node 22 LTS is recommended. The detected Node version is $(node --version)."
}

if (-not (Test-Path $Python)) {
    Write-Host "Creating Python virtual environment..."
    python -m venv $VenvDir
}

$PythonFingerprint = (
    Get-FileHash (Join-Path $Root "live_trading\pyproject.toml")
).Hash + (
    Get-FileHash (Join-Path $Root "backtesting\pyproject.toml")
).Hash
$PythonStamp = Join-Path $StateDir "python-dependencies.txt"
if (-not (Test-Path $PythonStamp) -or (Get-Content $PythonStamp -Raw) -ne $PythonFingerprint) {
    Write-Host "Installing Python packages..."
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -e "$Root\live_trading[test]" -e "$Root\backtesting[test]"
    Set-Content -LiteralPath $PythonStamp -Value $PythonFingerprint -NoNewline
}

$NodeFingerprint = (Get-FileHash (Join-Path $WebDir "package.json")).Hash
$NodeStamp = Join-Path $StateDir "node-dependencies.txt"
if (-not (Test-Path (Join-Path $WebDir "node_modules")) -or -not (Test-Path $NodeStamp) -or (Get-Content $NodeStamp -Raw) -ne $NodeFingerprint) {
    Write-Host "Installing web packages..."
    Push-Location $WebDir
    try {
        npm install
        npm run build
    }
    finally {
        Pop-Location
    }
    Set-Content -LiteralPath $NodeStamp -Value $NodeFingerprint -NoNewline
}
elseif (-not (Test-Path (Join-Path $WebDir ".next\BUILD_ID"))) {
    Push-Location $WebDir
    try { npm run build } finally { Pop-Location }
}

$ApiOut = Join-Path $StateDir "api.out.log"
$ApiErr = Join-Path $StateDir "api.err.log"
$WebOut = Join-Path $StateDir "web.out.log"
$WebErr = Join-Path $StateDir "web.err.log"

$Api = Start-Process -FilePath $Python `
    -ArgumentList "-m", "uvicorn", "live_trading.control.app:app", "--host", "127.0.0.1", "--port", "8765" `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $ApiOut -RedirectStandardError $ApiErr
$Web = Start-Process -FilePath "node.exe" `
    -ArgumentList $NextEntry, "start", "-H", "127.0.0.1", "-p", "3000" `
    -WorkingDirectory $WebDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $WebOut -RedirectStandardError $WebErr

@{
    api = $Api.Id
    web = $Web.Id
    started_at = [DateTime]::UtcNow.ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath $PidFile

function Wait-ForHealth([string]$Url, [string]$Name) {
    for ($Attempt = 0; $Attempt -lt 90; $Attempt++) {
        try {
            $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($Response.StatusCode -eq 200) {
                Write-Host "$Name is ready."
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "$Name did not become healthy. Check .app logs."
}

try {
    Wait-ForHealth "http://127.0.0.1:8765/api/health" "FastAPI"
    Wait-ForHealth "http://127.0.0.1:3000" "Next.js"
    if (-not $SkipBrowser) {
        Start-Process "http://127.0.0.1:3000"
    }
    Write-Host "Prediction-market application running at http://127.0.0.1:3000"
    Write-Host "Use .\stop.ps1 to stop it cleanly."
    if (-not $Detach) {
        try {
            Wait-Process -Id $Api.Id, $Web.Id
        }
        finally {
            & (Join-Path $Root "stop.ps1")
        }
    }
}
catch {
    & (Join-Path $Root "stop.ps1")
    throw
}
