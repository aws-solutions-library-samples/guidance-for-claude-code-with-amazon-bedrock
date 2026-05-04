# credential-process.ps1 — Drop-in replacement for credential-process.exe
# AWS credential_process protocol: outputs JSON credentials to stdout
# Usage: powershell.exe -ExecutionPolicy Bypass -NoProfile -File credential-process.ps1 -ProfileName ClaudeCode
#
# All user-facing messages go to stderr. Only the JSON credential goes to stdout.

param(
    [Alias("p")]
    [string]$ProfileName,
    [Alias("v")]
    [switch]$Version,
    [switch]$GetMonitoringToken,
    [switch]$ClearCache,
    [switch]$CheckExpiration,
    [switch]$RefreshIfNeeded
)

$ScriptVersion = "2.0.0-ps1"
$RedirectPort = 8400
$RedirectUri = "http://localhost:${RedirectPort}/callback"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Stderr($msg) { [Console]::Error.WriteLine($msg) }

function Debug-Print($msg) {
    if ($env:COGNITO_AUTH_DEBUG -match "^(1|true|yes)$") {
        Write-Stderr "Debug: $msg"
    }
}

# ── Config Loading ───────────────────────────────────────────────────────────

function Load-Config {
    # Try same directory as script, then ~/claude-code-with-bedrock/
    $scriptDir = Split-Path -Parent $PSCommandPath
    $configPath = Join-Path $scriptDir "config.json"
    if (-not (Test-Path $configPath)) {
        $configPath = Join-Path $env:USERPROFILE "claude-code-with-bedrock\config.json"
    }
    if (-not (Test-Path $configPath)) {
        throw "config.json not found in script directory or $env:USERPROFILE\claude-code-with-bedrock\"
    }

    $raw = Get-Content -Raw $configPath | ConvertFrom-Json

    # New format (profiles key) or old format (top-level profile names)
    if ($raw.PSObject.Properties["profiles"]) {
        $cfg = $raw.profiles.$ProfileName
        if (-not $cfg) { throw "Profile '$ProfileName' not found in config.json" }
    } else {
        $cfg = $raw.$ProfileName
        if (-not $cfg) { throw "Profile '$ProfileName' not found in config.json" }
    }

    # Legacy field mapping
    if (-not $cfg.provider_domain -and $cfg.okta_domain) { $cfg | Add-Member -NotePropertyName provider_domain -NotePropertyValue $cfg.okta_domain -Force }
    if (-not $cfg.client_id -and $cfg.okta_client_id) { $cfg | Add-Member -NotePropertyName client_id -NotePropertyValue $cfg.okta_client_id -Force }

    # Defaults
    if (-not $cfg.aws_region) { $cfg | Add-Member -NotePropertyName aws_region -NotePropertyValue "us-east-1" -Force }
    if (-not $cfg.provider_type) { $cfg | Add-Member -NotePropertyName provider_type -NotePropertyValue "auto" -Force }
    if (-not $cfg.credential_storage) { $cfg | Add-Member -NotePropertyName credential_storage -NotePropertyValue "session" -Force }

    # Auto-detect federation type
    if (-not $cfg.federation_type) {
        if ($cfg.federated_role_arn) {
            $cfg | Add-Member -NotePropertyName federation_type -NotePropertyValue "direct" -Force
        } else {
            $cfg | Add-Member -NotePropertyName federation_type -NotePropertyValue "cognito" -Force
        }
    }

    if (-not $cfg.max_session_duration) {
        $dur = if ($cfg.federation_type -eq "direct") { 43200 } else { 28800 }
        $cfg | Add-Member -NotePropertyName max_session_duration -NotePropertyValue $dur -Force
    }

    return $cfg
}

# ── Provider Detection ───────────────────────────────────────────────────────

function Detect-ProviderType($domain) {
    if (-not $domain) { return "oidc" }
    $uri = if ($domain -match "^https?://") { [uri]$domain } else { [uri]"https://$domain" }
    $h = $uri.Host.ToLower()

    if ($h -match "\.(okta|oktapreview|okta-emea)\.com$" -or $h -match "^(okta|oktapreview|okta-emea)\.com$") { return "okta" }
    if ($h -match "\.auth0\.com$" -or $h -eq "auth0.com") { return "auth0" }
    if ($h -match "\.microsoftonline\.com$" -or $h -match "\.windows\.net$") { return "azure" }
    if ($h -match "\.amazoncognito\.com$") { return "cognito" }
    if ($h -match "^cognito-idp\." -and $h -match "\.amazonaws\.com") { return "cognito" }
    return "oidc"
}

function Get-ProviderEndpoints($type) {
    switch ($type) {
        "okta"    { return @{ auth = "/oauth2/v1/authorize";   token = "/oauth2/v1/token";   scopes = "openid profile email" } }
        "auth0"   { return @{ auth = "/authorize";             token = "/oauth/token";       scopes = "openid profile email" } }
        "azure"   { return @{ auth = "/oauth2/v2.0/authorize"; token = "/oauth2/v2.0/token"; scopes = "openid profile email" } }
        "cognito" { return @{ auth = "/oauth2/authorize";      token = "/oauth2/token";      scopes = "openid email" } }
        default   { throw "Unknown provider type: $type" }
    }
}

# ── JWT Decode ───────────────────────────────────────────────────────────────

function Decode-JwtPayload($token) {
    $parts = $token.Split(".")
    if ($parts.Count -ne 3) { throw "Invalid JWT" }
    $payload = $parts[1].Replace("-", "+").Replace("_", "/")
    while ($payload.Length % 4) { $payload += "=" }
    $json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload))
    return $json | ConvertFrom-Json
}

# ── Credential Cache (session file mode) ─────────────────────────────────────

function Get-CachedCredentials {
    $credFile = Join-Path $env:USERPROFILE ".aws\credentials"
    if (-not (Test-Path $credFile)) { return $null }

    $content = Get-Content -Raw $credFile
    # Simple INI parser for the profile section
    $inSection = $false
    $creds = @{}
    foreach ($line in $content -split "`n") {
        $line = $line.Trim()
        if ($line -match "^\[(.+)\]$") {
            $inSection = ($Matches[1] -eq $ProfileName)
            continue
        }
        if ($inSection -and $line -match "^([^=]+?)\s*=\s*(.+)$") {
            $creds[$Matches[1].Trim()] = $Matches[2].Trim()
        }
    }

    if (-not $creds["aws_access_key_id"] -or -not $creds["aws_secret_access_key"] -or -not $creds["aws_session_token"]) {
        return $null
    }
    if ($creds["aws_access_key_id"] -eq "EXPIRED") { return $null }

    # Check expiration
    $expStr = $creds["x-expiration"]
    if ($expStr) {
        try {
            $exp = [DateTimeOffset]::Parse($expStr)
            $remaining = ($exp - [DateTimeOffset]::UtcNow).TotalSeconds
            if ($remaining -le 30) { return $null }
        } catch {
            return $null
        }
    }

    return @{
        Version = 1
        AccessKeyId = $creds["aws_access_key_id"]
        SecretAccessKey = $creds["aws_secret_access_key"]
        SessionToken = $creds["aws_session_token"]
        Expiration = $creds["x-expiration"]
    }
}

function Save-Credentials($creds) {
    $credFile = Join-Path $env:USERPROFILE ".aws\credentials"
    $dir = Split-Path $credFile
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    # Read existing content, replace or add our section
    $lines = @()
    $inSection = $false
    $sectionWritten = $false

    if (Test-Path $credFile) {
        foreach ($line in Get-Content $credFile) {
            if ($line -match "^\[(.+)\]$") {
                if ($inSection) {
                    # We were in our section, it's now ended — we already skipped it
                    $inSection = $false
                }
                if ($Matches[1] -eq $ProfileName) {
                    $inSection = $true
                    # Write our new section
                    $lines += "[$ProfileName]"
                    $lines += "aws_access_key_id = $($creds.AccessKeyId)"
                    $lines += "aws_secret_access_key = $($creds.SecretAccessKey)"
                    $lines += "aws_session_token = $($creds.SessionToken)"
                    if ($creds.Expiration) { $lines += "x-expiration = $($creds.Expiration)" }
                    $sectionWritten = $true
                    continue
                }
            }
            if (-not $inSection) { $lines += $line }
        }
    }

    if (-not $sectionWritten) {
        $lines += "[$ProfileName]"
        $lines += "aws_access_key_id = $($creds.AccessKeyId)"
        $lines += "aws_secret_access_key = $($creds.SecretAccessKey)"
        $lines += "aws_session_token = $($creds.SessionToken)"
        if ($creds.Expiration) { $lines += "x-expiration = $($creds.Expiration)" }
    }

    $tmpFile = "$credFile.tmp"
    $lines | Set-Content -Path $tmpFile -Encoding UTF8
    Move-Item -Path $tmpFile -Destination $credFile -Force
}

function Clear-CachedCredentials {
    $expired = @{
        AccessKeyId = "EXPIRED"; SecretAccessKey = "EXPIRED"
        SessionToken = "EXPIRED"; Expiration = "2000-01-01T00:00:00Z"
    }
    Save-Credentials $expired
    Write-Stderr "Cleared cached credentials for profile '$ProfileName'"
}

# ── Monitoring Token ─────────────────────────────────────────────────────────

function Get-MonitoringToken {
    # Check environment first
    if ($env:CLAUDE_CODE_MONITORING_TOKEN) { return $env:CLAUDE_CODE_MONITORING_TOKEN }

    $tokenFile = Join-Path $env:USERPROFILE ".claude-code-session\${ProfileName}-monitoring.json"
    if (-not (Test-Path $tokenFile)) { return $null }

    try {
        $data = Get-Content -Raw $tokenFile | ConvertFrom-Json
        $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        if (($data.expires - $now) -gt 600) { return $data.token }
    } catch {}
    return $null
}

function Save-MonitoringToken($idToken, $claims) {
    try {
        $dir = Join-Path $env:USERPROFILE ".claude-code-session"
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

        $data = @{
            token = $idToken
            expires = if ($claims.exp) { [int64]$claims.exp } else { 0 }
            email = if ($claims.email) { $claims.email } else { "" }
            profile = $ProfileName
        }
        $data | ConvertTo-Json | Set-Content -Path (Join-Path $dir "${ProfileName}-monitoring.json") -Encoding UTF8
        $env:CLAUDE_CODE_MONITORING_TOKEN = $idToken
        Debug-Print "Saved monitoring token"
    } catch {
        Debug-Print "Warning: Could not save monitoring token: $_"
    }
}

# ── PKCE ─────────────────────────────────────────────────────────────────────

function New-PKCE {
    $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
    $bytes = New-Object byte[] 32
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $verifier = [Convert]::ToBase64String($bytes) -replace '\+','-' -replace '/','_' -replace '='

    $sha = [System.Security.Cryptography.SHA256]::Create()
    $hash = $sha.ComputeHash([System.Text.Encoding]::ASCII.GetBytes($verifier))
    $sha.Dispose()
    $challenge = [Convert]::ToBase64String($hash) -replace '\+','-' -replace '/','_' -replace '='

    return @{ Verifier = $verifier; Challenge = $challenge }
}

function New-RandomString($length = 16) {
    $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
    $bytes = New-Object byte[] $length
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return [Convert]::ToBase64String($bytes) -replace '\+','-' -replace '/','_' -replace '='
}

# ── OIDC Authentication ─────────────────────────────────────────────────────

function Invoke-OIDCAuth($cfg, $providerType, $endpoints) {
    $state = New-RandomString
    $nonce = New-RandomString
    $pkce = New-PKCE

    $domain = $cfg.provider_domain
    if ($providerType -eq "azure" -and $domain.EndsWith("/v2.0")) {
        $domain = $domain.Substring(0, $domain.Length - 5)
    }
    $baseUrl = "https://$domain"

    # Build auth URL
    $scopes = [uri]::EscapeDataString($endpoints.scopes)
    $authUrl = "${baseUrl}$($endpoints.auth)?" +
        "client_id=$($cfg.client_id)" +
        "&response_type=code" +
        "&scope=$scopes" +
        "&redirect_uri=$([uri]::EscapeDataString($RedirectUri))" +
        "&state=$state" +
        "&nonce=$nonce" +
        "&code_challenge_method=S256" +
        "&code_challenge=$($pkce.Challenge)"

    if ($providerType -eq "azure") {
        $authUrl += "&response_mode=query&prompt=select_account"
    }

    # Start HTTP listener for callback
    $listener = [System.Net.HttpListener]::new()
    $listener.Prefixes.Add("http://localhost:${RedirectPort}/")
    try {
        $listener.Start()
    } catch {
        throw "Cannot listen on port $RedirectPort - another authentication may be in progress"
    }

    # Open browser
    Debug-Print "Opening browser for authentication..."
    Start-Process $authUrl

    # Wait for callback (5 min timeout)
    $task = $listener.GetContextAsync()
    if (-not $task.Wait(300000)) {
        $listener.Stop()
        throw "Authentication timeout - no response within 5 minutes"
    }

    $context = $task.Result
    $query = [System.Web.HttpUtility]::ParseQueryString($context.Request.Url.Query)

    # Send response to browser
    $html = [System.Text.Encoding]::UTF8.GetBytes(
        "<html><head><title>Authentication</title></head>" +
        "<body style='font-family:sans-serif;text-align:center;padding:50px'>" +
        "<h1>Authentication successful!</h1><p>Return to your terminal to continue.</p></body></html>"
    )
    $context.Response.ContentType = "text/html"
    $context.Response.ContentLength64 = $html.Length
    $context.Response.OutputStream.Write($html, 0, $html.Length)
    $context.Response.Close()
    $listener.Stop()

    # Check for errors
    if ($query["error"]) {
        $desc = if ($query["error_description"]) { $query["error_description"] } else { $query["error"] }
        throw "Authentication error: $desc"
    }
    if ($query["state"] -ne $state -or -not $query["code"]) {
        throw "Invalid state or missing authorization code"
    }

    $authCode = $query["code"]

    # Exchange code for tokens
    $tokenUrl = "${baseUrl}$($endpoints.token)"
    $tokenBody = @{
        grant_type    = "authorization_code"
        code          = $authCode
        redirect_uri  = $RedirectUri
        client_id     = $cfg.client_id
        code_verifier = $pkce.Verifier
    }

    $tokenResponse = Invoke-RestMethod -Uri $tokenUrl -Method POST -Body $tokenBody -ContentType "application/x-www-form-urlencoded"

    if (-not $tokenResponse.id_token) {
        throw "Token exchange failed: no id_token in response"
    }

    $claims = Decode-JwtPayload $tokenResponse.id_token

    # Validate nonce
    if ($claims.nonce -and $claims.nonce -ne $nonce) {
        throw "Invalid nonce in ID token"
    }

    return @{ IDToken = $tokenResponse.id_token; Claims = $claims }
}

# ── AWS Credential Exchange ──────────────────────────────────────────────────

function Get-AWSCredentials-Direct($cfg, $idToken, $claims) {
    Debug-Print "Using Direct STS federation (AssumeRoleWithWebIdentity)"

    $roleArn = $cfg.federated_role_arn
    if (-not $roleArn) { throw "federated_role_arn is required for direct STS federation" }

    # Build session name
    $sessionName = "claude-code"
    if ($claims.sub) {
        $sanitized = ($claims.sub -replace '[^\w+=,.@\-]', '-')
        if ($sanitized.Length -gt 32) { $sanitized = $sanitized.Substring(0, 32) }
        $sessionName = "claude-code-$sanitized"
    } elseif ($claims.email) {
        $emailPart = ($claims.email -split '@')[0]
        $sanitized = ($emailPart -replace '[^\w+=,.@\-]', '-')
        if ($sanitized.Length -gt 32) { $sanitized = $sanitized.Substring(0, 32) }
        $sessionName = "claude-code-$sanitized"
    }

    $duration = if ($cfg.max_session_duration) { $cfg.max_session_duration } else { 43200 }

    # Call STS AssumeRoleWithWebIdentity (unsigned — no AWS creds needed)
    $stsUrl = "https://sts.$($cfg.aws_region).amazonaws.com/"
    $body = "Action=AssumeRoleWithWebIdentity" +
        "&Version=2011-06-15" +
        "&RoleArn=$([uri]::EscapeDataString($roleArn))" +
        "&RoleSessionName=$([uri]::EscapeDataString($sessionName))" +
        "&WebIdentityToken=$([uri]::EscapeDataString($idToken))" +
        "&DurationSeconds=$duration"

    Debug-Print "Assuming role: $roleArn"
    Debug-Print "Session name: $sessionName"

    try {
        [xml]$response = Invoke-RestMethod -Uri $stsUrl -Method POST -Body $body -ContentType "application/x-www-form-urlencoded"
    } catch {
        $errMsg = $_.Exception.Message
        if ($errMsg -match "InvalidIdentityToken|ExpiredToken|Incorrect token audience") {
            Clear-CachedCredentials
            throw "Authentication failed - cached credentials cleared. Please try again.`nOriginal error: $errMsg"
        }
        throw "STS AssumeRoleWithWebIdentity failed: $errMsg"
    }

    $creds = $response.AssumeRoleWithWebIdentityResponse.AssumeRoleWithWebIdentityResult.Credentials

    return @{
        Version = 1
        AccessKeyId = $creds.AccessKeyId
        SecretAccessKey = $creds.SecretAccessKey
        SessionToken = $creds.SessionToken
        Expiration = $creds.Expiration
    }
}

function Get-AWSCredentials-Cognito($cfg, $idToken, $claims) {
    Debug-Print "Using Cognito Identity Pool federation"

    $region = $cfg.aws_region
    $identityPoolId = $cfg.identity_pool_id
    if (-not $identityPoolId -and $cfg.identity_pool_name -and -not $cfg.federated_role_arn) {
        $identityPoolId = $cfg.identity_pool_name
    }
    if (-not $identityPoolId) { throw "identity_pool_id is required for Cognito federation" }

    # Determine login key
    if ($claims.iss) {
        $loginKey = $claims.iss -replace "^https://", ""
    } else {
        $loginKey = $cfg.provider_domain
    }

    $cognitoUrl = "https://cognito-identity.$region.amazonaws.com/"
    $headers = @{ "Content-Type" = "application/x-amz-json-1.1" }

    # GetId
    $headers["X-Amz-Target"] = "AWSCognitoIdentityService.GetId"
    $getIdBody = @{
        IdentityPoolId = $identityPoolId
        Logins = @{ $loginKey = $idToken }
    } | ConvertTo-Json -Compress

    Debug-Print "Calling GetId with identity pool: $identityPoolId"
    try {
        $getIdResponse = Invoke-RestMethod -Uri $cognitoUrl -Method POST -Headers $headers -Body $getIdBody
    } catch {
        $errMsg = $_.Exception.Message
        if ($errMsg -match "NotAuthorizedException|InvalidParameterException|Token is not from a supported provider") {
            Clear-CachedCredentials
            throw "Authentication failed - cached credentials cleared. Please try again.`nOriginal error: $errMsg"
        }
        throw "Cognito GetId failed: $errMsg"
    }

    $identityId = $getIdResponse.IdentityId
    Debug-Print "Got Identity ID: $identityId"

    # GetCredentialsForIdentity
    $headers["X-Amz-Target"] = "AWSCognitoIdentityService.GetCredentialsForIdentity"
    $getCredsBody = @{
        IdentityId = $identityId
        Logins = @{ $loginKey = $idToken }
    } | ConvertTo-Json -Compress

    $credsResponse = Invoke-RestMethod -Uri $cognitoUrl -Method POST -Headers $headers -Body $getCredsBody
    $creds = $credsResponse.Credentials

    # Cognito returns epoch seconds for Expiration
    $expDate = (Get-Date "1970-01-01T00:00:00Z").AddSeconds($creds.Expiration).ToString("yyyy-MM-ddTHH:mm:ssZ")

    return @{
        Version = 1
        AccessKeyId = $creds.AccessKeyId
        SecretAccessKey = $creds.SecretKey   # Note: Cognito returns SecretKey, not SecretAccessKey
        SessionToken = $creds.SessionToken
        Expiration = $expDate
    }
}

# ── Port Lock ────────────────────────────────────────────────────────────────

function Test-PortAvailable($port) {
    try {
        $tcp = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
        $tcp.Start()
        $tcp.Stop()
        return $true
    } catch {
        return $false
    }
}

function Wait-ForPortRelease($port, $timeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortAvailable $port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# ── Main Flow ────────────────────────────────────────────────────────────────

function Main {
    # Load System.Web for HttpUtility
    Add-Type -AssemblyName System.Web

    # Resolve profile name
    if (-not $ProfileName) {
        $ProfileName = if ($env:CCWB_PROFILE) { $env:CCWB_PROFILE } else { "ClaudeCode" }
    }

    # Handle --version
    if ($Version) {
        Write-Output "credential-process $ScriptVersion"
        exit 0
    }

    # Load config
    try {
        $cfg = Load-Config
    } catch {
        Write-Stderr "Error: $_"
        exit 1
    }

    # Resolve provider type
    $providerType = $cfg.provider_type
    if ($providerType -eq "auto" -or -not $providerType) {
        $providerType = Detect-ProviderType $cfg.provider_domain
        if ($providerType -eq "oidc") {
            Write-Stderr "Error: Unable to auto-detect provider type for domain '$($cfg.provider_domain)'"
            exit 1
        }
    }

    $endpoints = Get-ProviderEndpoints $providerType

    # Handle --clear-cache
    if ($ClearCache) {
        Clear-CachedCredentials
        exit 0
    }

    # Handle --get-monitoring-token
    if ($GetMonitoringToken) {
        $token = Get-MonitoringToken
        if ($token) {
            Write-Output $token
            exit 0
        }
        # No cached token — trigger auth
        Debug-Print "No valid monitoring token found, triggering authentication..."
        try {
            $auth = Invoke-OIDCAuth $cfg $providerType $endpoints
            if ($cfg.federation_type -eq "direct") {
                $awsCreds = Get-AWSCredentials-Direct $cfg $auth.IDToken $auth.Claims
            } else {
                $awsCreds = Get-AWSCredentials-Cognito $cfg $auth.IDToken $auth.Claims
            }
            Save-Credentials $awsCreds
            Save-MonitoringToken $auth.IDToken $auth.Claims
            Write-Output $auth.IDToken
            exit 0
        } catch {
            Debug-Print "Authentication failed: $_"
            exit 1
        }
    }

    # Handle --check-expiration
    if ($CheckExpiration) {
        $cached = Get-CachedCredentials
        if ($cached) {
            Write-Stderr "Credentials valid for profile '$ProfileName'"
            exit 0
        } else {
            Write-Stderr "Credentials expired or missing for profile '$ProfileName'"
            exit 1
        }
    }

    # Handle --refresh-if-needed
    if ($RefreshIfNeeded) {
        $cached = Get-CachedCredentials
        if ($cached) {
            Debug-Print "Credentials still valid for profile '$ProfileName', no refresh needed"
            exit 0
        }
        # Fall through to normal auth flow
    }

    # ── Normal credential_process flow ──

    try {
        # Step 1: Check cache
        $cached = Get-CachedCredentials
        if ($cached) {
            $cached | ConvertTo-Json -Compress | Write-Output
            exit 0
        }

        # Step 2: Port lock
        if (-not (Test-PortAvailable $RedirectPort)) {
            Debug-Print "Another authentication is in progress, waiting..."
            if (Wait-ForPortRelease $RedirectPort) {
                $cached = Get-CachedCredentials
                if ($cached) {
                    $cached | ConvertTo-Json -Compress | Write-Output
                    exit 0
                }
            } else {
                Debug-Print "Authentication timeout or failed in another process"
                exit 1
            }
        }

        # Step 3: Check cache again (race condition guard)
        $cached = Get-CachedCredentials
        if ($cached) {
            $cached | ConvertTo-Json -Compress | Write-Output
            exit 0
        }

        # Step 4: OIDC Authentication
        Debug-Print "Authenticating with $providerType for profile '$ProfileName'..."
        $auth = Invoke-OIDCAuth $cfg $providerType $endpoints

        # Step 5: Get AWS credentials
        Debug-Print "Exchanging token for AWS credentials..."
        if ($cfg.federation_type -eq "direct") {
            $awsCreds = Get-AWSCredentials-Direct $cfg $auth.IDToken $auth.Claims
        } else {
            $awsCreds = Get-AWSCredentials-Cognito $cfg $auth.IDToken $auth.Claims
        }

        # Step 6: Cache + save monitoring token
        Save-Credentials $awsCreds
        Save-MonitoringToken $auth.IDToken $auth.Claims

        Debug-Print "Successfully obtained credentials, expires: $($awsCreds.Expiration)"

        # Step 7: Output
        $awsCreds | ConvertTo-Json -Compress | Write-Output
        exit 0

    } catch {
        $errMsg = "$_"
        if ($errMsg -notmatch "timeout") {
            Write-Stderr "Error: $errMsg"
        }

        if ($errMsg -match "NotAuthorizedException.*Token is not from a supported provider") {
            Write-Stderr "`nAuthentication failed: Token provider mismatch"
            Write-Stderr "Identity pool expects tokens from a specific provider configuration."
            Write-Stderr "Please verify your Cognito Identity Pool is configured correctly."
        }

        exit 1
    }
}

Main
