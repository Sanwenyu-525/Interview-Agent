[CmdletBinding()]
param(
    [ValidateSet("start", "desktop", "stop", "restart", "status", "logs")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$RuntimeRoot = Join-Path $ProjectRoot ".runtime"
$StatePath = Join-Path $RuntimeRoot "dev-services.json"
$BackendPort = 8000
$FrontendPort = 4173

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

function Get-ListenProcessIds {
    param([int]$Port)

    try {
        return @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
    } catch {
        return @()
    }
}

function Get-ProcessCommandLine {
    param([int]$ProcessId)

    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($processInfo) {
        return $processInfo.CommandLine
    }
    return ""
}

function Get-ProcessTree {
    param([int[]]$RootProcessIds)

    $allProcessIds = @($RootProcessIds | Where-Object { $_ -gt 0 } | Select-Object -Unique)
    $changed = $true
    while ($changed) {
        $changed = $false
        $children = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ParentProcessId -in $allProcessIds -and $_.ProcessId -notin $allProcessIds })
        foreach ($child in $children) {
            $allProcessIds += [int]$child.ProcessId
            $changed = $true
        }
    }
    return @($allProcessIds | Select-Object -Unique)
}

function Get-StateProcessIds {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        return @()
    }

    try {
        $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        return @($state.backend_pid, $state.frontend_pid, $state.desktop_pid) |
            Where-Object { $_ -and $_ -gt 0 -and (Get-ProcessCommandLine -ProcessId $_) -match "interview_agent.server|npm|vite|tauri" }
    } catch {
        return @()
    }
}

function Stop-ListeningServices {
    param(
        [int[]]$Ports,
        [int[]]$AdditionalProcessIds = @()
    )

    $processIds = @(
        foreach ($port in $Ports) {
            Get-ListenProcessIds -Port $port
        }
        $AdditionalProcessIds
    ) | Where-Object { $_ -gt 0 } | Select-Object -Unique

    if (-not $processIds) {
        return
    }

    $treeProcessIds = Get-ProcessTree -RootProcessIds $processIds
    foreach ($processId in $treeProcessIds) {
        $commandLine = Get-ProcessCommandLine -ProcessId $processId
        Write-Host "Stopping process $processId $commandLine"
    }
    foreach ($processId in ($treeProcessIds | Sort-Object -Descending)) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 300
}

function Wait-ForHttp {
    param([string]$Uri, [int]$TimeoutSeconds = 20)

    $attempts = $TimeoutSeconds * 3
    for ($attempt = 0; $attempt -lt $attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
        }
        Start-Sleep -Milliseconds 300
    }
    return $false
}

function Start-DevServices {
    Write-Host "Stopping old backend/frontend processes..."
    Stop-ListeningServices -Ports @($BackendPort, $FrontendPort) -AdditionalProcessIds (Get-StateProcessIds)

    $backendLog = Join-Path $RuntimeRoot "backend.log"
    $backendErrorLog = Join-Path $RuntimeRoot "backend.error.log"
    $frontendLog = Join-Path $RuntimeRoot "frontend.log"
    $frontendErrorLog = Join-Path $RuntimeRoot "frontend.error.log"

    $pythonCommand = if ($env:PYTHON) { $env:PYTHON } else { "python" }
    $env:PYTHONPATH = $ProjectRoot
    $env:INTERVIEW_AGENT_DB = Join-Path $ProjectRoot "interview-agent.db"

    $backendStartOptions = @{
        FilePath = $pythonCommand
        ArgumentList = @("-m", "interview_agent.server")
        WorkingDirectory = $ProjectRoot
        RedirectStandardOutput = $backendLog
        RedirectStandardError = $backendErrorLog
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $backendProcess = Start-Process @backendStartOptions

    $isWindowsHost = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
    $frontendCommand = if ($isWindowsHost) { "cmd.exe" } else { "npm" }
    $frontendArguments = if ($isWindowsHost) {
        @("/d", "/c", "npm run dev -- --host 0.0.0.0 --port $FrontendPort --strictPort")
    } else {
        @("run", "dev", "--", "--host", "0.0.0.0", "--port", "$FrontendPort", "--strictPort")
    }
    $frontendStartOptions = @{
        FilePath = $frontendCommand
        ArgumentList = $frontendArguments
        WorkingDirectory = $FrontendRoot
        RedirectStandardOutput = $frontendLog
        RedirectStandardError = $frontendErrorLog
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $frontendProcess = Start-Process @frontendStartOptions

    [ordered]@{
        backend_pid = $backendProcess.Id
        frontend_pid = $frontendProcess.Id
        started_at = (Get-Date).ToString("o")
    } | ConvertTo-Json | Set-Content -Path $StatePath -Encoding utf8

    $backendReady = Wait-ForHttp -Uri "http://127.0.0.1:$BackendPort/settings/llm/profiles"
    $frontendReady = Wait-ForHttp -Uri "http://127.0.0.1:$FrontendPort"
    if (-not $backendReady -or -not $frontendReady) {
        Write-Host "Startup failed. Run .\dev.ps1 logs to inspect logs." -ForegroundColor Red
        exit 1
    }

    Write-Host "Backend ready: http://127.0.0.1:$BackendPort"
    Write-Host "Frontend ready: http://127.0.0.1:$FrontendPort"
}

function Start-DesktopService {
    Write-Host "Starting Tauri desktop app..."
    Stop-ListeningServices -Ports @($BackendPort, $FrontendPort) -AdditionalProcessIds (Get-StateProcessIds)

    $desktopLog = Join-Path $RuntimeRoot "desktop.log"
    $desktopErrorLog = Join-Path $RuntimeRoot "desktop.error.log"
    $env:PYTHONPATH = $ProjectRoot
    $env:INTERVIEW_AGENT_DB = Join-Path $ProjectRoot "interview-agent.db"

    $desktopStartOptions = @{
        FilePath = "cmd.exe"
        ArgumentList = @("/d", "/c", "npm run tauri dev")
        WorkingDirectory = $FrontendRoot
        RedirectStandardOutput = $desktopLog
        RedirectStandardError = $desktopErrorLog
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $desktopProcess = Start-Process @desktopStartOptions

    [ordered]@{
        desktop_pid = $desktopProcess.Id
        started_at = (Get-Date).ToString("o")
        mode = "desktop"
    } | ConvertTo-Json | Set-Content -Path $StatePath -Encoding utf8

    $backendReady = Wait-ForHttp -Uri "http://127.0.0.1:$BackendPort/settings/llm/profiles" -TimeoutSeconds 60
    $frontendReady = Wait-ForHttp -Uri "http://127.0.0.1:$FrontendPort" -TimeoutSeconds 60
    if (-not $backendReady -or -not $frontendReady) {
        Write-Host "Desktop startup failed. Run .\dev.bat logs to inspect logs." -ForegroundColor Red
        exit 1
    }

    Write-Host "Desktop app is starting. Backend: http://127.0.0.1:$BackendPort"
}

function Show-DevStatus {
    foreach ($service in @(
        @{ Name = "backend"; Port = $BackendPort },
        @{ Name = "frontend"; Port = $FrontendPort }
    )) {
        $processIds = @(Get-ListenProcessIds -Port $service.Port)
        if ($processIds) {
            $details = $processIds | ForEach-Object { "$_ $((Get-ProcessCommandLine -ProcessId $_).Trim())" }
            Write-Host "$($service.Name): running on port $($service.Port); $($details -join '; ')" -ForegroundColor Green
        } else {
            Write-Host "$($service.Name): stopped; port $($service.Port)" -ForegroundColor Yellow
        }
    }

    $desktopProcessIds = @(Get-StateProcessIds | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    if ($desktopProcessIds) {
        $details = $desktopProcessIds | ForEach-Object { "$($_) $((Get-ProcessCommandLine -ProcessId $_).Trim())" }
        Write-Host "desktop: running; $($details -join '; ')" -ForegroundColor Green
    } else {
        Write-Host "desktop: stopped" -ForegroundColor Yellow
    }
}

if ($Action -eq "start") {
    Start-DevServices
} elseif ($Action -eq "desktop") {
    Start-DesktopService
} elseif ($Action -eq "stop") {
    Stop-ListeningServices -Ports @($BackendPort, $FrontendPort) -AdditionalProcessIds (Get-StateProcessIds)
    if (Test-Path -LiteralPath $StatePath) {
        Remove-Item -LiteralPath $StatePath -Force
    }
    Write-Host "Backend and frontend stopped."
} elseif ($Action -eq "restart") {
    $restartAction = "desktop"
    if (Test-Path -LiteralPath $StatePath) {
        try {
            $previousState = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
            if ($previousState.mode -ne "desktop") {
                $restartAction = "start"
            }
        } catch {
        }
    }
    Stop-ListeningServices -Ports @($BackendPort, $FrontendPort) -AdditionalProcessIds (Get-StateProcessIds)
    if ($restartAction -eq "desktop") {
        Start-DesktopService
    } else {
        Start-DevServices
    }
} elseif ($Action -eq "status") {
    Show-DevStatus
} elseif ($Action -eq "logs") {
        foreach ($logPath in @(
            (Join-Path $RuntimeRoot "backend.log"),
            (Join-Path $RuntimeRoot "backend.error.log"),
            (Join-Path $RuntimeRoot "frontend.log"),
            (Join-Path $RuntimeRoot "frontend.error.log"),
            (Join-Path $RuntimeRoot "desktop.log"),
            (Join-Path $RuntimeRoot "desktop.error.log")
    )) {
        if (Test-Path -LiteralPath $logPath) {
            Write-Host "===== $logPath ====="
            Get-Content -LiteralPath $logPath -Tail 40
        }
    }
}
