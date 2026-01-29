<#
.SYNOPSIS
    Quick Start - One command to run the AI Orchestration Stack

.DESCRIPTION
    This is the simplest way to start the AI stack. Just run this script!

.EXAMPLE
    .\Quick-Start.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Quick-Start.ps1
#>

Write-Host @"

    ╔═══════════════════════════════════════════════════╗
    ║     AI Orchestration Stack - Quick Start          ║
    ╚═══════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan

$ErrorActionPreference = "SilentlyContinue"

# Step 1: Check Ollama
Write-Host "[1/4] Checking Ollama installation..." -ForegroundColor Yellow
$ollamaInstalled = Get-Command ollama -ErrorAction SilentlyContinue

if (-not $ollamaInstalled) {
    # Check common paths
    $paths = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:ProgramFiles\Ollama\ollama.exe"
    )
    $found = $paths | Where-Object { Test-Path $_ } | Select-Object -First 1

    if ($found) {
        $env:PATH += ";$(Split-Path $found)"
    }
    else {
        Write-Host ""
        Write-Host "  Ollama not found!" -ForegroundColor Red
        Write-Host "  Please install Ollama from: https://ollama.ai/download/windows" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  After installing, run this script again." -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
}
Write-Host "  Ollama found!" -ForegroundColor Green

# Step 2: Start Ollama
Write-Host "[2/4] Starting Ollama server..." -ForegroundColor Yellow
$ollamaRunning = $false
try {
    $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3
    $ollamaRunning = $true
    Write-Host "  Ollama already running!" -ForegroundColor Green
}
catch {
    Write-Host "  Starting Ollama..." -ForegroundColor Cyan
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5

    # Wait for startup
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 2
            $ollamaRunning = $true
            break
        }
        catch {
            Start-Sleep -Seconds 1
            Write-Host "." -NoNewline
        }
    }
    Write-Host ""
}

if (-not $ollamaRunning) {
    Write-Host "  Failed to start Ollama!" -ForegroundColor Red
    exit 1
}
Write-Host "  Ollama is running!" -ForegroundColor Green

# Step 3: Check/Pull Model
Write-Host "[3/4] Checking for AI model..." -ForegroundColor Yellow
$hasModel = $false
try {
    $models = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 10
    if ($models.models.Count -gt 0) {
        $hasModel = $true
        Write-Host "  Found $($models.models.Count) model(s):" -ForegroundColor Green
        $models.models | ForEach-Object { Write-Host "    - $($_.name)" -ForegroundColor Cyan }
    }
}
catch {}

if (-not $hasModel) {
    Write-Host "  No models found. Pulling llama2 (this may take a few minutes)..." -ForegroundColor Yellow
    & ollama pull llama2
    Write-Host "  Model downloaded!" -ForegroundColor Green
}

# Step 4: Ready!
Write-Host "[4/4] Stack is ready!" -ForegroundColor Yellow
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  AI Orchestration Stack is now running!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Ollama API:    http://localhost:11434" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Quick test command:" -ForegroundColor Yellow
Write-Host '    ollama run llama2 "Hello, how are you?"' -ForegroundColor White
Write-Host ""
Write-Host "  Or use the API:" -ForegroundColor Yellow
Write-Host '    Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post -Body (@{model="llama2";prompt="Hello"} | ConvertTo-Json)' -ForegroundColor White
Write-Host ""
Write-Host "  To stop Ollama:" -ForegroundColor Yellow
Write-Host '    Get-Process ollama | Stop-Process' -ForegroundColor White
Write-Host ""
Write-Host "Press Enter to open interactive chat, or Ctrl+C to exit..." -ForegroundColor Cyan
Read-Host

# Launch interactive chat
& ollama run llama2
