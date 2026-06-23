<#
.SYNOPSIS
    Build the Windows credential-process.exe and otel-helper.exe locally with Nuitka.

.DESCRIPTION
    Workaround for the broken AWS CodeBuild Windows pipeline (see
    windows-build-error.md). Our CodeBuild image's Python has a broken TLS cert
    store, so Nuitka can't download the MinGW/winlibs toolchain from GitHub and
    the build dies with CERTIFICATE_VERIFY_FAILED. A real Windows machine has a
    working cert store, so the *same* Nuitka build just succeeds here.

    This script mirrors deployment/infrastructure/codebuild-windows.yaml exactly
    (same Nuitka flags, same deps), but runs on a local Windows box instead of
    CodeBuild. It builds both .exe files from the current source tree, so it
    includes all SmartNews customizations (Honeycomb, Codex, awsAuthRefresh, etc.).

.PREREQUISITES
    - Windows 10/11 (x64)
    - Python 3.12 installed and on PATH (python --version -> 3.12.x).
      Get it from https://www.python.org/downloads/ or `choco install python312`.
    - Internet access to github.com (for Nuitka's one-time MinGW download).

.USAGE
    From the repo root (the folder that contains the `source` directory):

        powershell -ExecutionPolicy Bypass -File scripts\build-windows-local.ps1

    Output: credential-process-windows.exe and otel-helper-windows.exe in
    .\dist-windows\. Hand those to whoever packages the Windows distribution.
#>

$ErrorActionPreference = "Stop"

# --- Locate Python 3.12 -----------------------------------------------------
# Prefer the standard choco/python.org install path, fall back to PATH.
$python = "C:\Python312\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}
Write-Host "Using Python: $python"
& $python --version

# --- Resolve repo root (script lives in <repo>/scripts) ---------------------
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
Write-Host "Repo root: $repoRoot"

if (-not (Test-Path "source\credential_provider\__main__.py")) {
    Write-Error "Cannot find source\credential_provider\__main__.py - run this from the repo, with the source tree present."
    exit 1
}

# --- Install build + application dependencies (mirrors the buildspec) -------
Write-Host "`n=== Installing build dependencies ==="
& $python -m pip install --upgrade pip
& $python -m pip install nuitka==2.7.12 ordered-set zstandard
& $python -m pip install boto3 requests PyJWT cryptography
& $python -m pip install keyring pywin32
& $python -m pip install questionary rich cleo pydantic pyyaml

# --- Output directory -------------------------------------------------------
$outDir = Join-Path $repoRoot "dist-windows"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# --- Build credential-process-windows.exe -----------------------------------
# Flags identical to codebuild-windows.yaml:155. The first Nuitka run downloads
# the MinGW/winlibs toolchain from GitHub (this is the step that fails in
# CodeBuild but succeeds on a real Windows machine).
Write-Host "`n=== Building credential-process-windows.exe ==="
& $python -m nuitka `
    --standalone --onefile --assume-yes-for-downloads `
    --company-name="Claude Code" `
    --product-name="Claude Code Credential Process" `
    --file-version="1.0.0.0" --product-version="1.0.0.0" `
    --windows-file-description="AWS Credential Process for Claude Code" `
    --include-package=keyring.backends `
    --output-filename=credential-process-windows.exe `
    --output-dir="$outDir" --remove-output `
    source\credential_provider\__main__.py

# --- Build otel-helper-windows.exe ------------------------------------------
# Flags identical to codebuild-windows.yaml:157.
Write-Host "`n=== Building otel-helper-windows.exe ==="
& $python -m nuitka `
    --standalone --onefile --assume-yes-for-downloads `
    --company-name="Claude Code" `
    --product-name="Claude Code OTEL Helper" `
    --file-version="1.0.0.0" --product-version="1.0.0.0" `
    --windows-file-description="OpenTelemetry Helper for Claude Code" `
    --output-filename=otel-helper-windows.exe `
    --output-dir="$outDir" --remove-output `
    source\otel_helper\__main__.py

# --- Validate -- fail loudly if either binary is missing --------------------
Write-Host "`n=== Build results ==="
$cred = Join-Path $outDir "credential-process-windows.exe"
$otel = Join-Path $outDir "otel-helper-windows.exe"
if (-not (Test-Path $cred)) { Write-Error "FATAL: credential-process-windows.exe was not produced."; exit 1 }
if (-not (Test-Path $otel)) { Write-Error "FATAL: otel-helper-windows.exe was not produced."; exit 1 }
Get-ChildItem $outDir\*.exe | ForEach-Object { Write-Host ("{0} - {1:N0} bytes" -f $_.Name, $_.Length) }

Write-Host "`nDone. Binaries are in: $outDir"
