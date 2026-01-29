@echo off
REM AI Orchestration Stack - Windows Quick Start Batch File
REM
REM Double-click this file or run from Command Prompt to start the AI stack.
REM
REM If you get execution policy errors, run this in PowerShell:
REM   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
REM

echo.
echo =============================================
echo   AI Orchestration Stack - Starting...
echo =============================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Run PowerShell script with bypass
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0Quick-Start.ps1"

if errorlevel 1 (
    echo.
    echo Failed to start AI stack!
    pause
)
