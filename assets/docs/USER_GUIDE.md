# End User Guide

This guide is for developers who receive a Claude Code installation package from their IT administrator. It covers what the package is, how to install it, how it integrates with Claude Code, and what to expect during daily use.

---

## What You're Getting

Your administrator has set up a system that lets you use Claude Code with Amazon Bedrock using your corporate login (Okta, Azure AD, Auth0, or Cognito). Instead of managing API keys, you authenticate with your existing corporate credentials and receive temporary AWS credentials automatically.

The package you receive contains:

| File | Purpose |
|------|---------|
| `install.sh` | Installer for macOS and Linux |
| `install.bat` | Installer for Windows |
| `credential-process-macos-arm64` | Authentication binary for Apple Silicon Macs |
| `credential-process-macos-intel` | Authentication binary for Intel Macs |
| `credential-process-linux-x64` | Authentication binary for Linux x86_64 |
| `credential-process-linux-arm64` | Authentication binary for Linux ARM64 |
| `credential-process-windows.exe` | Authentication binary for Windows |
| `config.json` | Configuration (OIDC provider, AWS region, model) |
| `claude-settings/settings.json` | Claude Code environment settings |
| `otel-helper-*` | Telemetry helper (only if monitoring is enabled) |

Not all files will be present — your administrator builds for the platforms your organization uses.

---

## Prerequisites

You need:

- **AWS CLI v2** installed — [installation instructions](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- **Claude Code** installed
- **A web browser** for SSO authentication
- **Corporate credentials** — your normal login for Okta, Azure AD, Auth0, or Cognito

You do **not** need:
- An AWS account
- Python, Poetry, or Git
- Any API keys or AWS access keys

---

## Installation

### macOS / Linux

1. Unzip or extract the package to a temporary location
2. Open a terminal and navigate to that directory
3. Run the installer:
   ```bash
   chmod +x install.sh
   ./install.sh
   ```

### Windows

1. Extract the package to a temporary folder
2. Double-click `install.bat` (or right-click → Run as Administrator if needed)

### What the Installer Does

The installer performs these steps automatically:

1. **Checks prerequisites** — verifies AWS CLI is installed
2. **Detects your platform** — picks the correct binary for your OS and architecture
3. **Copies files** — installs the credential-process binary and config to `~/claude-code-with-bedrock/` (or `%USERPROFILE%\claude-code-with-bedrock\` on Windows)
4. **Configures AWS CLI** — adds a profile entry to `~/.aws/config` that tells AWS CLI to use the credential-process binary for authentication
5. **Installs Claude Code settings** — copies `settings.json` to `~/.claude/settings.json`, configuring Claude Code to use Bedrock with the correct model and region

If you already have Claude Code settings (`~/.claude/settings.json`), the installer asks whether to overwrite them.

### After Installation — File Layout

```
~/claude-code-with-bedrock/
├── credential-process      # The authentication binary
├── config.json             # Federation and OIDC configuration
└── otel-helper             # Telemetry helper (if monitoring enabled)

~/.aws/config               # Modified — new profile added
~/.claude/settings.json     # Modified — Bedrock configuration
```

The AWS CLI config entry looks like:
```ini
[profile ClaudeCode]
credential_process = /Users/you/claude-code-with-bedrock/credential-process --profile ClaudeCode
region = us-east-1
```

The Claude Code settings contain:
```json
{
  "env": {
    "AWS_REGION": "us-east-1",
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "AWS_PROFILE": "ClaudeCode",
    "ANTHROPIC_MODEL": "us.anthropic.claude-sonnet-4-20250514-v1:0"
  }
}
```

---

## How It Works

### The Authentication Flow

When Claude Code (or any AWS tool) needs credentials:

1. AWS CLI sees the `credential_process` setting in `~/.aws/config`
2. It runs the `credential-process` binary
3. The binary checks for cached credentials — if they're still valid, it returns them immediately (no browser interaction)
4. If credentials are expired or missing, the binary opens your **default web browser** to your corporate login page
5. You authenticate with your normal corporate credentials (Okta, Azure AD, etc.)
6. The browser redirects back to `localhost:8400/callback` — the binary's local server receives the authentication code
7. The binary exchanges the code for an OIDC token, then exchanges that token for temporary AWS credentials
8. The credentials are cached and returned to AWS CLI
9. Claude Code uses the credentials to call Amazon Bedrock

**You only interact with step 5** — logging in when prompted. Everything else is automatic.

### Credential Lifecycle

| Federation Type | Session Duration | What Happens When It Expires |
|----------------|-----------------|------------------------------|
| Direct STS | Up to 12 hours | Browser opens for re-authentication |
| Cognito | Up to 8 hours | Browser opens for re-authentication |

Credentials are cached between uses. If you used Claude Code at 9 AM and come back at 2 PM, you won't need to re-authenticate (assuming Direct STS with 12-hour sessions). If you come back the next day, your browser will open briefly for a new login.

### Credential Storage

Your administrator chose one of two storage methods (you don't need to change this):

| Method | How It Works | What You'll Notice |
|--------|-------------|-------------------|
| **Keyring** | Credentials stored in your OS secure store (macOS Keychain, Windows Credential Manager, Linux Secret Service) | On macOS, you may see a Keychain access prompt on first use — click "Always Allow" |
| **Session Files** | Credentials stored as temporary files in `~/.aws/` | No system prompts, slightly less secure |

---

## Using Claude Code with Bedrock

Once installed, Claude Code uses Bedrock automatically. The settings installed to `~/.claude/settings.json` tell Claude Code:

- **Use Bedrock** instead of the Anthropic API (`CLAUDE_CODE_USE_BEDROCK=1`)
- **Which AWS profile** to use for credentials (`AWS_PROFILE=ClaudeCode`)
- **Which Claude model** to use (e.g., `ANTHROPIC_MODEL=us.anthropic.claude-sonnet-4-20250514-v1:0`)
- **Which AWS region** to send requests to (`AWS_REGION=us-east-1`)

### First Use

1. Open your terminal
2. Run Claude Code as you normally would
3. Your browser will open to your corporate login page
4. Log in with your corporate credentials
5. Return to your terminal — Claude Code is now authenticated and working

### Daily Use

After the first authentication, Claude Code works transparently. Credentials are cached, so you typically authenticate once per day (or once per session, depending on the session duration your administrator configured).

If your credentials expire mid-session, the browser will open briefly for re-authentication. This happens automatically — you just need to log in when prompted.

### Verifying It Works

You can verify your setup outside of Claude Code using the AWS CLI:

```bash
# Set the profile
export AWS_PROFILE=ClaudeCode

# Verify authentication — should show your federated identity
aws sts get-caller-identity
```

Expected output:
```json
{
    "UserId": "AROA...:claude-code-alice",
    "Account": "123456789012",
    "Arn": "arn:aws:sts::123456789012:assumed-role/BedrockFederatedRole/claude-code-alice"
}
```

If your browser opens during this test, log in and the command will complete.

### Multiple Profiles

If your organization provided a package with multiple profiles (e.g., for different environments), you switch between them by changing the `AWS_PROFILE` environment variable:

```bash
export AWS_PROFILE=ClaudeCode-Dev
# or
export AWS_PROFILE=ClaudeCode-Prod
```

---

## Quota Notifications

If your organization has quota monitoring enabled, you may see notifications about your token usage. For a full explanation of how quotas work, see the [Quota Management Guide](QUOTA_MANAGEMENT.md).

### Warning Notification

When you approach your usage limit (typically at 80% or 90%), a browser page opens briefly showing:

- Your current monthly and daily token consumption
- Your limits and percentage used
- A visual progress bar

This is informational — you can continue working. The notification is your organization's way of letting you know you're approaching your allocation.

### Blocked Notification

If your usage exceeds the limit and the policy enforcement mode is "block," you'll see:

```
============================================================
ACCESS BLOCKED - QUOTA EXCEEDED
============================================================

Your Claude Code access has been temporarily blocked due to
exceeding your token quota.

Current Usage:
  Monthly: 230,000,000 / 225,000,000 tokens (102.2%)
  Daily: 9,500,000 / 8,250,000 tokens (115.2%)

Policy: user:alice@company.com

To request an unblock, contact your administrator.
============================================================
```

A browser page also opens with a visual display of your usage.

**What to do:** Contact your administrator. They can:
- Temporarily unblock you (`ccwb quota unblock`)
- Increase your limit (`ccwb quota set-user`)
- Investigate whether the usage is expected

---

## Troubleshooting

### Browser doesn't open for authentication

The credential-process binary tries to open your default browser. If it fails:

1. Check the terminal output for a URL — you can copy and paste it into your browser manually
2. Make sure port 8400 on localhost is not blocked by a firewall or another process

### "No authorization code received" / Timeout

The authentication has a 5-minute timeout. If it fails:

1. Make sure you completed the login in your browser
2. Check that nothing is blocking `localhost:8400` (VPNs, corporate proxies)
3. Try again — transient network issues can cause timeouts

### "Token is not from a supported provider"

Your IdP token isn't being recognized by AWS. This is a configuration issue — contact your administrator.

### macOS Keychain prompts

On first use with keyring storage, macOS asks for Keychain access. Click **"Always Allow"** to prevent repeated prompts. If you accidentally clicked "Deny," you may need to:

1. Open Keychain Access
2. Find entries related to `credential-process`
3. Delete them and re-authenticate

### Credentials expired mid-session

This is normal. When credentials expire (8-12 hours depending on configuration), the next AWS API call triggers re-authentication. Your browser opens, you log in, and work continues. This may cause a brief pause in Claude Code while the authentication round-trip completes.

### "Access blocked — quota exceeded"

You've used your allocated tokens for the period. Contact your administrator. See [Quota Notifications](#quota-notifications) above.

### Clearing cached credentials

If you need to force re-authentication (e.g., after a role change in the IdP):

```bash
~/claude-code-with-bedrock/credential-process --clear-cache
```

### Checking credential status

To check if your credentials are still valid without triggering a refresh:

```bash
~/claude-code-with-bedrock/credential-process --check-expiration
# Exit code 0 = valid, 1 = expired
```

### Debug mode

For detailed logging (useful when reporting issues to your administrator):

```bash
COGNITO_AUTH_DEBUG=1 ~/claude-code-with-bedrock/credential-process --profile ClaudeCode
```

This prints the full authentication flow to stderr.

---

## What Data Is Collected

If your organization enabled monitoring, the following telemetry is sent to your organization's OpenTelemetry collector (not to Anthropic or any third party):

- **Token usage** — input/output/cache tokens per request
- **Code activity** — lines of code generated, files edited, programming languages
- **Operational metrics** — session duration, request counts
- **User attribution** — your email address (extracted from your IdP token) for usage dashboards

This data is used by your organization for cost attribution, capacity planning, and productivity insights. It stays within your organization's AWS account.

The `otel-helper` binary extracts your identity from the cached authentication token and adds it as headers to telemetry data. It does not access any of your code, files, or prompts.

---

## Uninstalling

### macOS / Linux

```bash
# Remove the installation
rm -rf ~/claude-code-with-bedrock

# Remove the AWS profile from ~/.aws/config
# Edit the file and delete the [profile ClaudeCode] section

# Optionally remove Claude Code settings
rm ~/.claude/settings.json
```

### Windows

```
# Remove the installation directory
rmdir /s %USERPROFILE%\claude-code-with-bedrock

# Remove the AWS profile
# Edit %USERPROFILE%\.aws\config and remove the [profile ClaudeCode] section

# Optionally remove Claude Code settings
del %USERPROFILE%\.claude\settings.json
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Verify authentication | `AWS_PROFILE=ClaudeCode aws sts get-caller-identity` |
| Force re-authentication | `~/claude-code-with-bedrock/credential-process --clear-cache` |
| Check credential status | `~/claude-code-with-bedrock/credential-process --check-expiration` |
| Debug authentication | `COGNITO_AUTH_DEBUG=1 ~/claude-code-with-bedrock/credential-process` |
| Test OTEL helper | `~/claude-code-with-bedrock/otel-helper --test` |
| Switch profiles | `export AWS_PROFILE=<profile-name>` |
