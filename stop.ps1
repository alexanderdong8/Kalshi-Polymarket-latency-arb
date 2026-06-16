$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root ".app\pids.json"

try {
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/api/shutdown" -TimeoutSec 15 | Out-Null
}
catch {
    Write-Host "Control service was not reachable; continuing with recorded processes."
}

$Processes = @()
if (Test-Path $PidFile) {
    $Recorded = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    $Processes = @($Recorded.api, $Recorded.web) | Where-Object { $_ }
}

$Deadline = [DateTime]::UtcNow.AddSeconds(12)
function Get-DescendantProcessIds([int]$ParentId) {
    $Found = @()
    $Queue = @($ParentId)
    while ($Queue.Count -gt 0) {
        $Current = $Queue[0]
        $Queue = @($Queue | Select-Object -Skip 1)
        $Children = @(
            Get-CimInstance Win32_Process -Filter "ParentProcessId = $Current" -ErrorAction SilentlyContinue
        )
        foreach ($Child in $Children) {
            $Found += [int]$Child.ProcessId
            $Queue += [int]$Child.ProcessId
        }
    }
    return $Found
}

foreach ($ProcessId in $Processes) {
    while ((Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $Deadline) {
        Start-Sleep -Milliseconds 300
    }
    $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($Process) {
        $Descendants = @(Get-DescendantProcessIds $ProcessId)
        [array]::Reverse($Descendants)
        foreach ($ChildId in $Descendants) {
            Stop-Process -Id $ChildId -Force -ErrorAction SilentlyContinue
        }
        Stop-Process -Id $ProcessId -Force
    }
}

function Stop-OrphanedAppPorts {
    $Connections = @(
        Get-NetTCPConnection -LocalPort 8765, 3000 -State Listen -ErrorAction SilentlyContinue
    )
    foreach ($Connection in $Connections) {
        $ProcessId = [int]$Connection.OwningProcess
        if ($Processes -contains $ProcessId) {
            continue
        }
        $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
        if (-not $ProcessInfo) {
            continue
        }
        $CommandLine = [string]$ProcessInfo.CommandLine
        $IsThisApp =
            $CommandLine.Contains("live_trading.control.app:app") -or
            (
                $CommandLine.Contains("node_modules\next\dist\bin\next") -and
                $CommandLine.Contains("prediction_markets_arb")
            )
        if ($IsThisApp) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

Stop-OrphanedAppPorts

if (Test-Path $PidFile) {
    Remove-Item -LiteralPath $PidFile
}
Write-Host "Prediction-market application stopped."
