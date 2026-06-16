@echo off
REM ABOUTME: Unified otel-helper entry point for Windows. Tries the fast Go binary first;
REM ABOUTME: if AV blocks it, falls back to the PowerShell script seamlessly.
REM
REM Claude Code invokes this via otelHeadersHelper. Output is JSON on stdout.
"%~dp0otel-helper.exe" %* 2>nul && exit /b 0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0otel-helper.ps1" %*
