# Claude Code Authentication Installer for Windows (generic)
param(
    [string]$ScriptDir = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)

$ErrorActionPreference = 'Stop'
Set-Location $ScriptDir

Write-Host '======================================'
Write-Host 'Claude Code Authentication Installer'
Write-Host '======================================'
Write-Host ''

# Check prerequisites
Write-Host 'Checking prerequisites...'
$hasErrors = $false

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host 'ERROR: AWS CLI is not installed'
    Write-Host '       Please install from https://aws.amazon.com/cli/'
    $hasErrors = $true
}

if (-not (Test-Path 'config.json')) {
    Write-Host 'ERROR: config.json not found in current directory'
    Write-Host '       Make sure you are running this from the extracted package folder'
    $hasErrors = $true
}

if (-not (Test-Path 'credential-process-windows.exe')) {
    Write-Host 'ERROR: credential-process-windows.exe not found'
    Write-Host '       The package may be incomplete or corrupted'
    $hasErrors = $true
}

if ($hasErrors) {
    Read-Host 'Press Enter to exit'
    exit 1
}

if (-not (Test-Path 'claude-settings/settings.json')) {
    Write-Host 'WARNING: claude-settings/settings.json not found'
    Write-Host '         Claude Code IDE settings will not be configured automatically'
    Write-Host ''
}

Write-Host 'OK Prerequisites validated'
Write-Host ''

# Create directory
Write-Host 'Installing authentication tools...'
$installDir = Join-Path $env:USERPROFILE 'claude-code-with-bedrock'
if (-not (Test-Path $installDir)) { New-Item -ItemType Directory -Path $installDir -Force | Out-Null }

# Copy credential process
Write-Host 'Copying credential process...'
Copy-Item -Force 'credential-process-windows.exe' (Join-Path $installDir 'credential-process.exe')

# Copy OTEL helper if it exists
if (Test-Path 'otel-helper-windows.exe') {
    Write-Host 'Copying OTEL helper...'
    Copy-Item -Force 'otel-helper-windows.exe' (Join-Path $installDir 'otel-helper.exe')
}

# Copy configuration
Write-Host 'Copying configuration...'
Copy-Item -Force 'config.json' $installDir

# Install Claude Code settings
$claudeDir = Join-Path $env:USERPROFILE '.claude'
if (Test-Path 'claude-settings/settings.json') {
    Write-Host ''
    Write-Host 'Installing Claude Code settings...'
    if (-not (Test-Path $claudeDir)) { New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null }

    $doWrite = $true
    $settingsTarget = Join-Path $claudeDir 'settings.json'
    if (Test-Path $settingsTarget) {
        Write-Host 'Existing Claude Code settings found'
        $backupName = "settings.json.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        $backupPath = Join-Path $claudeDir $backupName
        Copy-Item $settingsTarget $backupPath
        Write-Host "  Backed up to: $backupPath"
        $answer = Read-Host 'Overwrite with new settings? (Y/n)'
        if ($answer -and $answer -ne 'y' -and $answer -ne 'Y') {
            $doWrite = $false
            Write-Host 'Skipping Claude Code settings...'
        }
    }

    if ($doWrite) {
        $otelPath = ((Join-Path $installDir 'otel-helper.exe') -replace '\\', '/')
        $credPath = ((Join-Path $installDir 'credential-process.exe') -replace '\\', '/')
        $settings = Get-Content 'claude-settings/settings.json' -Raw | ConvertFrom-Json
        if ($settings.otelHeadersHelper) {
            $settings.otelHeadersHelper = "`"$otelPath`""
        }
        if ($settings.awsAuthRefresh) {
            $settings.awsAuthRefresh = $settings.awsAuthRefresh -replace '__CREDENTIAL_PROCESS_PATH__', "`"$credPath`""
        }
        $settings | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 $settingsTarget

        $settingsContent = Get-Content $settingsTarget -Raw
        if ($settingsContent -match '__CREDENTIAL_PROCESS_PATH__|__OTEL_HELPER_PATH__') {
            Write-Host 'WARNING: Some path placeholders were not replaced in settings.json'
            Write-Host "         You may need to edit the file manually: $settingsTarget"
        } else {
            Write-Host "OK Claude Code settings configured: $settingsTarget"
        }
    }
} else {
    Write-Host ''
    Write-Host 'WARNING: No claude-settings/settings.json found in package'
    Write-Host '         Skipping Claude Code IDE settings configuration'
}

# Configure AWS profiles
Write-Host ''
Write-Host 'Configuring AWS profiles...'
$configJson = Get-Content 'config.json' | ConvertFrom-Json
$profiles = $configJson.PSObject.Properties.Name

foreach ($p in $profiles) {
    Write-Host "Configuring AWS profile: $p"
    $region = $configJson.$p.aws_region
    if (-not $region) { $first = $profiles | Select-Object -First 1; $region = $configJson.$first.aws_region; if (-not $region) { $region = 'us-east-1' } }
    $credExe = (Join-Path $installDir 'credential-process.exe') -replace '\\', '/'
    $awsConfigDir = Join-Path $env:USERPROFILE '.aws'
    if (-not (Test-Path $awsConfigDir)) { New-Item -ItemType Directory -Path $awsConfigDir -Force | Out-Null }
    $awsConfigFile = Join-Path $awsConfigDir 'config'
    $profileBlock = "[profile $p]`ncredential_process = `"$credExe`" --profile $p`nregion = $region`n"
    if (Test-Path $awsConfigFile) {
        $lines = Get-Content $awsConfigFile
        $newLines = @()
        $skipSection = $false
        foreach ($line in $lines) {
            if ($line -match "^\[profile $p\]") {
                $skipSection = $true
                continue
            }
            if ($skipSection -and $line -match '^\[') {
                $skipSection = $false
            }
            if (-not $skipSection) {
                $newLines += $line
            }
        }
        while ($newLines.Count -gt 0 -and $newLines[-1] -eq '') { $newLines = $newLines[0..($newLines.Count-2)] }
        if ($newLines.Count -gt 0) {
            $newContent = ($newLines -join "`n") + "`n`n" + $profileBlock
        } else {
            $newContent = $profileBlock
        }
    } else {
        $newContent = $profileBlock
    }
    [System.IO.File]::WriteAllText($awsConfigFile, $newContent)
    Write-Host "  OK Created AWS profile '$p'"
}

# Per-zone isolation: print per-zone inference-profile ARNs that users
# must configure in Claude Code. No PowerShell wrapper is installed — IAM
# enforces zone isolation on its own, and the wrapper approach was too
# fragile across IDE integrations, PowerShell 5 vs 7 $PROFILE differences,
# non-interactive shells, scheduled tasks, and constrained language mode.
# Users configure ANTHROPIC_MODEL explicitly in whichever way fits.
$firstProfileName = $profiles | Select-Object -First 1
$firstProfileCfg = $configJson.$firstProfileName
if ($firstProfileCfg.enforce_project_isolation) {
    # Clean up any legacy wrapper artifacts from previous installs that
    # shipped the shell-function approach. Safe no-ops if absent.
    $legacyWrapper = Join-Path $installDir 'claude-wrapper.ps1'
    if (Test-Path $legacyWrapper) {
        Remove-Item $legacyWrapper -Force -ErrorAction SilentlyContinue
        Write-Host "  Removed legacy claude-wrapper.ps1"
    }
    if (Test-Path $PROFILE) {
        $profileContent = Get-Content $PROFILE -Raw
        if ($profileContent -and $profileContent.Contains('# >>> ccwb claude wrapper >>>')) {
            # Strip the marker block in place
            $stripped = [regex]::Replace($profileContent, '(?s)\r?\n*# >>> ccwb claude wrapper >>>.*?# <<< ccwb claude wrapper <<<\r?\n*', "`r`n")
            $stripped = $stripped.TrimEnd() + "`r`n"
            Set-Content -Path $PROFILE -Value $stripped -Encoding UTF8
            Write-Host "  Removed legacy ccwb claude wrapper block from `$PROFILE"
        }
    }

    # IMPORTANT: these Write-Host lines use SINGLE quotes so PowerShell does
    # NOT interpolate `$env:AWS_REGION` / `$env:ANTHROPIC_MODEL` at install
    # time. We want the literal text to land in the user's terminal so they
    # know which commands to run; double-quoting would expand the vars to
    # whatever is already in the installer's environment (often empty or
    # stale), producing misleading output like "eu-west-3 = '<region ...>'".
    Write-Host ''
    Write-Host '=========================================================================='
    Write-Host 'Next step: configure your model + region'
    Write-Host '=========================================================================='
    Write-Host ''
    Write-Host 'Before running claude, set BOTH the AWS region and the model ARN'
    Write-Host '(your admin will give you both - they are paired per zone):'
    Write-Host ''
    Write-Host '    $env:AWS_REGION = ''<region provided by your team>''     # e.g. eu-west-3'
    Write-Host '    $env:ANTHROPIC_MODEL = ''<arn provided by your team>'''
    Write-Host ''
    Write-Host 'Add those two lines to $PROFILE to persist across PowerShell sessions.'
    Write-Host ''
    Write-Host 'Both must be set together. If only ANTHROPIC_MODEL is set, the AWS SDK'
    Write-Host 'defaults to a different region and rejects the call with "invalid ARN".'
    Write-Host '=========================================================================='
}

# Post-install validation
Write-Host ''
Write-Host 'Validating installation...'
$credBinary = Join-Path $installDir 'credential-process.exe'
if (Test-Path $credBinary) {
    Write-Host "  OK credential-process.exe: $credBinary"
} else {
    Write-Host "  FAIL credential-process.exe not found at: $credBinary"
}
$settingsFile = Join-Path (Join-Path $env:USERPROFILE '.claude') 'settings.json'
if (Test-Path $settingsFile) {
    Write-Host "  OK settings.json: $settingsFile"
} else {
    Write-Host "  WARN settings.json not found at: $settingsFile"
}

Write-Host ''
Write-Host '======================================'
Write-Host 'Installation complete!'
Write-Host '======================================'
Write-Host ''
Write-Host 'Available profiles:'
foreach ($p in $profiles) { Write-Host "  - $p" }
Write-Host ''
Write-Host 'To use Claude Code authentication:'
Write-Host '  set AWS_PROFILE=<profile-name>'
Write-Host '  aws sts get-caller-identity'
Write-Host ''
$first = $profiles | Select-Object -First 1
Write-Host "Example:"
Write-Host "  set AWS_PROFILE=$first"
Write-Host '  aws sts get-caller-identity'
Write-Host ''
Write-Host 'Note: Authentication will automatically open your browser when needed.'
