# ABOUTME: PowerShell port of otel-helper for Windows environments where the
# ABOUTME: Go binary is blocked by antivirus. Full parity with the Go binary:
# ABOUTME: sidecar management, cache check, Bearer splice, cache-miss TTL, token refresh.
#
# Usage: powershell.exe -NoProfile -ExecutionPolicy Bypass -File otel-helper.ps1
#
# This script implements the same logic as otel-helper.exe / otel-helper.sh:
# 1. Ensure OTEL collector sidecar is running (if in sidecar mode)
# 2. Check file cache for valid (non-expired) OTEL headers
# 3. If valid, serve them (splicing Bearer token from env/monitoring cache)
# 4. If expired/missing, write empty-headers cache with TTL (anti-hammering)
# 5. Trigger credential-process for token refresh in background
#
# The key advantage: this avoids invoking otel-helper-windows.exe entirely,
# which is flagged by some AV solutions as an unsigned/unknown binary.

param(
    [string]$Profile = $env:AWS_PROFILE
)

if (-not $Profile) { $Profile = "ClaudeCode" }

$installDir = Join-Path $env:USERPROFILE "claude-code-with-bedrock"
$cacheDir = Join-Path $env:USERPROFILE ".claude-code-session"
$cacheFile = Join-Path $cacheDir "$Profile-otel-headers.json"
$rawFile = Join-Path $cacheDir "$Profile-otel-headers.raw"
$monitoringFile = Join-Path $cacheDir "$Profile-monitoring.json"
$pidFile = Join-Path $installDir "collector.pid"

# Anti-hammering TTL: how long an empty-headers cache entry is valid (seconds).
# Matches the Go binary's emptyHeadersCacheTTLSeconds constant.
$emptyHeadersCacheTTL = 120

# Ensure cache directory exists
if (-not (Test-Path $cacheDir)) {
    New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
}

# --- Sidecar collector management ---
# Start the local OTEL collector if in sidecar mode (binary + config present)
# Uses a dedicated <profile>-collector AWS profile so the Go SDK resolves
# credentials via credential_process (same as otel-helper.sh).
$otelcol = Join-Path $installDir "otelcol.exe"
$collectorConfig = Join-Path $installDir "collector-config.yaml"
if ((Test-Path $otelcol) -and (Test-Path $collectorConfig)) {
    $collectorRunning = $false
    if (Test-Path $pidFile) {
        $pid = Get-Content $pidFile -ErrorAction SilentlyContinue
        if ($pid) {
            try {
                $proc = Get-Process -Id ([int]$pid) -ErrorAction SilentlyContinue
                if ($proc -and -not $proc.HasExited) { $collectorRunning = $true }
            } catch { }
        }
    }
    if (-not $collectorRunning) {
        try {
            $logFile = Join-Path $cacheDir "collector.log"
            $env:AWS_PROFILE = "$Profile-collector"
            $proc = Start-Process -FilePath $otelcol -ArgumentList "--config", $collectorConfig `
                -RedirectStandardOutput $logFile -RedirectStandardError $logFile `
                -WindowStyle Hidden -PassThru -ErrorAction SilentlyContinue
            if ($proc) {
                Set-Content -Path $pidFile -Value $proc.Id
            }
            $env:AWS_PROFILE = $Profile
        } catch {
            # Collector start failed - non-fatal, continue without sidecar
        }
    }
}

# --- Cache check (Layer 1) ---
if ((Test-Path $cacheFile) -and (Test-Path $rawFile)) {
    try {
        $cacheContent = Get-Content $cacheFile -Raw | ConvertFrom-Json
        $tokenExp = [long]$cacheContent.token_exp
        $now = [long](Get-Date -UFormat %s)

        if ($tokenExp -gt ($now + 60)) {
            # Token still valid (>60s remaining) - serve cached attribution headers
            $rawContent = (Get-Content $rawFile -Raw).Trim()

            # Resolve Bearer token: env var first, then monitoring cache
            $token = $env:CLAUDE_CODE_MONITORING_TOKEN
            if (-not $token -and (Test-Path $monitoringFile)) {
                try {
                    $monData = Get-Content $monitoringFile -Raw | ConvertFrom-Json
                    $token = $monData.token
                } catch {
                    # Monitoring file unreadable - continue without token
                }
            }

            if ($token) {
                # Splice Bearer token into the raw JSON headers
                # Raw file is like: {"x-user-email": "user@example.com"} or {}
                $trimmed = $rawContent.TrimEnd('}').TrimEnd()
                if ($trimmed -match '[^\s{]$') {
                    # Has content after '{' -> need a comma separator
                    Write-Output "$trimmed, `"authorization`": `"Bearer $token`"}"
                } else {
                    # Empty object '{'
                    Write-Output "$trimmed`"authorization`": `"Bearer $token`"}"
                }
            } else {
                # No token resolvable - serve attribution headers as-is
                Write-Output $rawContent
            }
            exit 0
        }
    } catch {
        # Cache parse error - fall through to refresh
    }
}

# --- Cache miss / expired ---
# Write empty-headers cache with short TTL (anti-hammering).
# This prevents credential-process from being spawned on every invocation
# within the TTL window when auth is persistently failing.
# Only write if the cache file doesn't exist or is already empty/stale
# (mirrors otel.EmptyHeadersWriteSafe logic — don't clobber valid attribution).
$shouldWriteEmpty = $true
if (Test-Path $cacheFile) {
    try {
        $existing = Get-Content $cacheFile -Raw | ConvertFrom-Json
        # If existing cache has non-empty headers (schema_version present and headers non-empty),
        # don't overwrite with empty — a transient read failure shouldn't erase good data
        if ($existing.headers -and ($existing.headers | Get-Member -MemberType NoteProperty).Count -gt 0) {
            $shouldWriteEmpty = $false
        }
    } catch { }
}

if ($shouldWriteEmpty) {
    $now = [long](Get-Date -UFormat %s)
    $emptyCache = @{
        schema_version = 2
        headers = @{}
        token_exp = $now + $emptyHeadersCacheTTL
        cached_at = $now
    } | ConvertTo-Json -Compress
    $emptyRaw = "{}"
    try {
        Set-Content -Path $cacheFile -Value $emptyCache -NoNewline
        Set-Content -Path $rawFile -Value $emptyRaw -NoNewline
    } catch { }
}

# Trigger credential-process for token refresh in background (non-blocking).
# credential-process --get-monitoring-token writes the monitoring token cache;
# with Option 3 (separate PR), it will also write the otel-headers cache directly.
$credProcess = Join-Path $installDir "credential-process.exe"
if (Test-Path $credProcess) {
    try {
        Start-Process -FilePath $credProcess -ArgumentList "--get-monitoring-token", "--profile", $Profile -WindowStyle Hidden -ErrorAction SilentlyContinue
    } catch {
        # credential-process unavailable - nothing we can do
    }
}

# Emit valid empty JSON to satisfy the otelHeadersHelper contract
Write-Output "{}"
