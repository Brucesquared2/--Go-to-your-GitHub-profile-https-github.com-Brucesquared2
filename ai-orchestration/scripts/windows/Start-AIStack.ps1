<#
.SYNOPSIS
    AI Orchestration Stack - Windows Startup Script

.DESCRIPTION
    This script starts the complete AI orchestration stack on Windows including:
    - Ollama server
    - AI Orchestrator service
    - Optional WSL2 integration for kernel module

.PARAMETER NoOllama
    Skip Ollama startup (assumes already running)

.PARAMETER Debug
    Enable debug mode with verbose logging

.PARAMETER Foreground
    Run orchestrator in foreground (don't run as background job)

.PARAMETER Model
    Ensure specific Ollama model is available

.PARAMETER OllamaHost
    Ollama host URL (default: http://localhost:11434)

.EXAMPLE
    .\Start-AIStack.ps1
    Start everything with defaults

.EXAMPLE
    .\Start-AIStack.ps1 -Foreground -Debug
    Run in foreground with debug logging

.EXAMPLE
    .\Start-AIStack.ps1 -Model "codellama"
    Start and ensure codellama model is available

.NOTES
    Author: Claude Code Project
    Version: 1.0.0
#>

[CmdletBinding()]
param(
    [switch]$NoOllama,
    [switch]$Debug,
    [switch]$Foreground,
    [string]$Model = "llama2",
    [string]$OllamaHost = "http://localhost:11434",
    [switch]$Help
)

# ============================================================================
# Configuration
# ============================================================================

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

# Paths
$OrchestratorDir = Join-Path $ProjectRoot "orchestrator"
$ConfigDir = Join-Path $ProjectRoot "config"
$LogDir = Join-Path $env:LOCALAPPDATA "ai-orchestrator\logs"
$PidDir = Join-Path $env:LOCALAPPDATA "ai-orchestrator\run"

# Ensure directories exist
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $PidDir | Out-Null

# ============================================================================
# Helper Functions
# ============================================================================

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] " -ForegroundColor Green -NoNewline
    Write-Host $Message
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline
    Write-Host $Message
}

function Write-Err {
    param([string]$Message)
    Write-Host "[ERROR] " -ForegroundColor Red -NoNewline
    Write-Host $Message
}

function Write-Dbg {
    param([string]$Message)
    if ($Debug) {
        Write-Host "[DEBUG] " -ForegroundColor Cyan -NoNewline
        Write-Host $Message
    }
}

function Test-OllamaRunning {
    try {
        $response = Invoke-RestMethod -Uri "$OllamaHost/api/tags" -Method Get -TimeoutSec 5 -ErrorAction SilentlyContinue
        return $true
    }
    catch {
        return $false
    }
}

function Test-CommandExists {
    param([string]$Command)
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Wait-ForService {
    param(
        [string]$Name,
        [scriptblock]$CheckScript,
        [int]$TimeoutSeconds = 30
    )

    Write-Info "Waiting for $Name to be ready..."

    $elapsed = 0
    while (-not (& $CheckScript)) {
        Start-Sleep -Seconds 1
        $elapsed++
        Write-Host "." -NoNewline

        if ($elapsed -ge $TimeoutSeconds) {
            Write-Host ""
            Write-Err "$Name failed to start within ${TimeoutSeconds}s"
            return $false
        }
    }
    Write-Host ""
    Write-Info "$Name is ready"
    return $true
}

# ============================================================================
# Component Functions
# ============================================================================

function Start-OllamaServer {
    Write-Info "Starting Ollama..."

    # Check if already running
    if (Test-OllamaRunning) {
        Write-Info "Ollama already running"
        return $true
    }

    # Check if Ollama is installed
    if (-not (Test-CommandExists "ollama")) {
        # Try common installation paths
        $ollamaPaths = @(
            "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
            "$env:ProgramFiles\Ollama\ollama.exe",
            "C:\Ollama\ollama.exe"
        )

        $ollamaExe = $ollamaPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

        if (-not $ollamaExe) {
            Write-Err "Ollama not found. Install from: https://ollama.ai/download/windows"
            return $false
        }

        $env:PATH += ";$(Split-Path $ollamaExe)"
    }

    # Start Ollama server
    Write-Info "Starting Ollama server..."

    $logFile = Join-Path $LogDir "ollama.log"

    $processInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processInfo.FileName = "ollama"
    $processInfo.Arguments = "serve"
    $processInfo.UseShellExecute = $false
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $processInfo.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($processInfo)

    # Save PID
    $process.Id | Out-File -FilePath (Join-Path $PidDir "ollama.pid")

    # Wait for Ollama to be ready
    $ready = Wait-ForService -Name "Ollama" -CheckScript { Test-OllamaRunning } -TimeoutSeconds 30

    if ($ready) {
        Write-Info "Ollama started (PID: $($process.Id))"
    }

    return $ready
}

function Invoke-EnsureModel {
    param([string]$ModelName)

    Write-Info "Checking for model: $ModelName"

    try {
        $models = Invoke-RestMethod -Uri "$OllamaHost/api/tags" -Method Get -TimeoutSec 10
        $modelExists = $models.models | Where-Object { $_.name -like "$ModelName*" }

        if ($modelExists) {
            Write-Info "Model $ModelName is available"
            return $true
        }
    }
    catch {
        Write-Dbg "Failed to list models: $_"
    }

    Write-Info "Pulling model: $ModelName (this may take a while)..."

    try {
        $pullProcess = Start-Process -FilePath "ollama" -ArgumentList "pull", $ModelName -Wait -PassThru -NoNewWindow

        if ($pullProcess.ExitCode -eq 0) {
            Write-Info "Model $ModelName pulled successfully"
            return $true
        }
    }
    catch {
        Write-Err "Failed to pull model: $_"
    }

    return $false
}

function Start-Orchestrator {
    Write-Info "Starting AI Orchestrator..."

    # Check Python
    if (-not (Test-CommandExists "python")) {
        if (-not (Test-CommandExists "python3")) {
            Write-Err "Python not found. Install from: https://python.org"
            return $false
        }
        $pythonCmd = "python3"
    }
    else {
        $pythonCmd = "python"
    }

    # Check/install dependencies
    Write-Dbg "Checking Python dependencies..."
    & $pythonCmd -c "import requests" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Info "Installing Python dependencies..."
        & $pythonCmd -m pip install requests
    }

    $orchestratorScript = Join-Path $OrchestratorDir "ai_orchestrator.py"

    if (-not (Test-Path $orchestratorScript)) {
        Write-Err "Orchestrator script not found: $orchestratorScript"
        return $false
    }

    $args = @()
    if ($Debug) { $args += "--debug" }
    $args += "--no-kernel"  # No kernel module on Windows
    $args += "start"

    if ($Foreground) {
        Write-Info "Running orchestrator in foreground..."
        & $pythonCmd $orchestratorScript @args
    }
    else {
        Write-Info "Running orchestrator as background job..."

        $logFile = Join-Path $LogDir "orchestrator.log"

        $job = Start-Job -ScriptBlock {
            param($python, $script, $arguments, $log)
            & $python $script @arguments 2>&1 | Out-File -FilePath $log -Append
        } -ArgumentList $pythonCmd, $orchestratorScript, $args, $logFile

        # Save job ID
        $job.Id | Out-File -FilePath (Join-Path $PidDir "orchestrator.jobid")

        Start-Sleep -Seconds 2

        if ($job.State -eq "Running") {
            Write-Info "Orchestrator started (Job ID: $($job.Id))"
            return $true
        }
        else {
            Write-Err "Orchestrator failed to start. Check: $logFile"
            return $false
        }
    }

    return $true
}

function Show-Status {
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host "  AI Orchestration Stack Status" -ForegroundColor Cyan
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host ""

    # Ollama status
    Write-Host "Ollama:         " -NoNewline
    if (Test-OllamaRunning) {
        Write-Host "RUNNING" -ForegroundColor Green

        try {
            $models = Invoke-RestMethod -Uri "$OllamaHost/api/tags" -Method Get -TimeoutSec 5
            $modelCount = ($models.models | Measure-Object).Count
            Write-Host "Models:         $modelCount available"
        }
        catch {}
    }
    else {
        Write-Host "STOPPED" -ForegroundColor Red
    }

    # Orchestrator status
    $jobIdFile = Join-Path $PidDir "orchestrator.jobid"
    Write-Host "Orchestrator:   " -NoNewline
    if (Test-Path $jobIdFile) {
        $jobId = Get-Content $jobIdFile
        $job = Get-Job -Id $jobId -ErrorAction SilentlyContinue
        if ($job -and $job.State -eq "Running") {
            Write-Host "RUNNING" -ForegroundColor Green -NoNewline
            Write-Host " (Job ID: $jobId)"
        }
        else {
            Write-Host "STOPPED" -ForegroundColor Red
        }
    }
    else {
        Write-Host "NOT STARTED" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Logs: $LogDir"
    Write-Host ""
}

function Stop-AllServices {
    Write-Info "Stopping AI Orchestration Stack..."

    # Stop orchestrator job
    $jobIdFile = Join-Path $PidDir "orchestrator.jobid"
    if (Test-Path $jobIdFile) {
        $jobId = Get-Content $jobIdFile
        $job = Get-Job -Id $jobId -ErrorAction SilentlyContinue
        if ($job) {
            Write-Info "Stopping orchestrator (Job ID: $jobId)..."
            Stop-Job -Job $job
            Remove-Job -Job $job -Force
        }
        Remove-Item $jobIdFile -Force
    }

    # Stop Ollama
    $ollamaPidFile = Join-Path $PidDir "ollama.pid"
    if (Test-Path $ollamaPidFile) {
        $pid = Get-Content $ollamaPidFile
        $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($process) {
            Write-Info "Stopping Ollama (PID: $pid)..."
            Stop-Process -Id $pid -Force
        }
        Remove-Item $ollamaPidFile -Force
    }

    Write-Info "Stack stopped"
}

function Show-Help {
    Get-Help $MyInvocation.MyCommand.Path -Detailed
}

# ============================================================================
# Main
# ============================================================================

if ($Help) {
    Show-Help
    exit 0
}

# Parse command from remaining arguments
$Command = "start"
if ($args.Count -gt 0) {
    $Command = $args[0]
}

switch ($Command.ToLower()) {
    "start" {
        Write-Host ""
        Write-Host "=========================================="  -ForegroundColor Cyan
        Write-Host "  AI Orchestration Stack - Windows" -ForegroundColor Cyan
        Write-Host "==========================================" -ForegroundColor Cyan
        Write-Host ""

        # Start Ollama
        if (-not $NoOllama) {
            if (-not (Start-OllamaServer)) {
                Write-Err "Failed to start Ollama"
                exit 1
            }

            # Ensure model
            if ($Model) {
                Invoke-EnsureModel -ModelName $Model | Out-Null
            }
        }

        # Start orchestrator
        if (-not (Start-Orchestrator)) {
            Write-Err "Failed to start orchestrator"
            exit 1
        }

        Write-Host ""
        Write-Info "AI Orchestration Stack started successfully!"
        Show-Status
    }
    "stop" {
        Stop-AllServices
    }
    "restart" {
        Stop-AllServices
        Start-Sleep -Seconds 2
        & $MyInvocation.MyCommand.Path @PSBoundParameters start
    }
    "status" {
        Show-Status
    }
    default {
        Write-Err "Unknown command: $Command"
        Write-Host "Valid commands: start, stop, restart, status"
        exit 1
    }
}
