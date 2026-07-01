# Local Testing Guide

Before distributing Claude Code authentication to your organization, thorough local testing ensures everything works perfectly. While the `ccwb test` command handles most validation automatically, this guide covers additional scenarios and performance testing for complete confidence in your deployment.

## The Power of Automated Testing

The CLI provides comprehensive automated testing that simulates exactly what your users will experience:

```bash
poetry run ccwb test         # Basic authentication test
poetry run ccwb test --api   # Full test including Bedrock API calls
```

This single command runs through the entire user journey - installation, authentication, and Bedrock access. For most deployments, this automated testing provides sufficient validation. However, understanding what happens behind the scenes and testing edge cases helps you support users more effectively.

## Understanding Your Deployed Infrastructure

Before testing the authentication flow, you might want to verify that your AWS infrastructure deployed correctly. The CloudFormation stacks created by `ccwb deploy` contain all the necessary components for authentication.

To check your authentication stack status:

```bash
# Check the auth stack (uses the identity pool name from your deployment)
poetry run ccwb status --detailed
```

This shows the status of all your deployed stacks.

A healthy deployment shows "CREATE_COMPLETE" or "UPDATE_COMPLETE". The stack outputs contain important values like the Identity Pool ID and IAM role ARN that enable the authentication flow. While you don't need to interact with these directly, understanding they exist helps when troubleshooting.

## Examining Your Distribution Package

The package created by `ccwb package` contains everything needed for end-user installation. Understanding its contents helps you support users and troubleshoot issues.

Explore the distribution directory:

```bash
ls -la dist/
```

You'll find platform-specific executables (credential-process-macos and credential-process-linux), the configuration file with your organization's settings, and the intelligent installer script. If monitoring is enabled, you'll also see OTEL helper executables and Claude Code settings.

The configuration file contains your OIDC provider details and the Cognito Identity Pool ID:

```bash
cat dist/config.json | jq .
```

This configuration gets copied to the user's home directory during installation, where the credential process reads it at runtime.

## Manual Installation Testing

While `ccwb test` handles most validation, you might want to manually walk through the installation process to understand the user experience better.

Create a test environment that simulates a fresh user installation:

```bash
mkdir -p ~/test-user
cp -r dist ~/test-user/
cd ~/test-user/dist
chmod +x install.sh
./install.sh
```

The installer detects your platform, copies the appropriate binary to `~/claude-code-with-bedrock/`, and configures the AWS CLI profile. This mimics exactly what your users will experience.

Test the authentication:

```bash
aws sts get-caller-identity --profile ClaudeCode
```

On first run, a browser window opens for authentication. After successful login, you'll see your federated AWS identity, confirming the entire flow works correctly.

## Testing Authentication Flows

Understanding how authentication works helps you support users effectively. The credential process implements sophisticated caching to minimize authentication prompts while maintaining security.

To force a fresh authentication and observe the complete flow:

```bash
# Clear any cached credentials (this replaces them with expired dummies to preserve keychain permissions)
~/claude-code-with-bedrock/credential-process --clear-cache

# Trigger authentication
aws sts get-caller-identity --profile ClaudeCode
```

Your browser opens to your organization's login page. After authentication, the terminal displays your federated identity.

Credentials are cached after the first authentication. Test this by making successive calls:

```bash
# First call - includes authentication
time aws sts get-caller-identity --profile ClaudeCode

# Second call - uses cached credentials
time aws sts get-caller-identity --profile ClaudeCode
```

The first call takes 3-10 seconds including authentication. Cached calls complete in under a second. Credentials remain valid for up to 8 hours.

## Validating Bedrock Access

With authentication working, verify that users can access Amazon Bedrock models as intended. Start by listing available Claude models:

```bash
aws bedrock list-foundation-models \
  --profile ClaudeCode \
  --region us-east-1 \
  --query 'modelSummaries[?contains(modelId, `claude`)].[modelId,modelName]' \
  --output table
```

This confirms your IAM permissions grant access to Bedrock models. For a complete end-to-end test, invoke a Claude model:

```bash
# Create a simple test prompt
echo '{
  "anthropic_version": "bedrock-2023-05-31",
  "messages": [{"role": "user", "content": "Say hello!"}],
  "max_tokens": 50
}' > test-prompt.json

# Invoke Claude
aws bedrock-runtime invoke-model \
  --profile ClaudeCode \
  --region us-east-1 \
  --model-id anthropic.claude-3-haiku-20240307-v1:0 \
  --body fileb://test-prompt.json \
  response.json

# View the response
jq -r '.content[0].text' response.json
```

If your deployment includes multiple Bedrock regions, test each one to ensure proper access:

```bash
for region in us-east-1 us-west-2 eu-west-1; do
  echo "Testing $region..."
  aws bedrock list-foundation-models \
    --profile ClaudeCode \
    --region $region \
    --query 'length(modelSummaries)' \
    --output text
done
```

## Claude Code Integration

The ultimate test involves using Claude Code with your authentication system. Set the AWS profile environment variable:

```bash
export AWS_PROFILE=ClaudeCode
```

If you enabled monitoring, verify the Claude Code settings were installed correctly:

```bash
cat ~/.claude/settings.json | jq '.env.OTEL_EXPORTER_OTLP_ENDPOINT'
```

Now launch Claude Code:

```bash
claude
```

Claude Code automatically uses the AWS profile for authentication. Behind the scenes, it calls the credential process whenever it needs to access Bedrock, with all authentication handled transparently.

### Important: AWS Credential Precedence

When testing, be aware that AWS CLI uses the following credential precedence order:

1. **Environment variables** (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`) - highest priority
2. Command line options
3. Environment variable `AWS_PROFILE`
4. Credential process from AWS config
5. Config file credentials
6. Instance metadata

If you have AWS credentials in environment variables (e.g., from other tools like Isengard), they will override the ClaudeCode profile. To ensure you're using the Claude Code authentication:

```bash
# Clear any existing AWS credentials from environment
unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY
unset AWS_SESSION_TOKEN

# Then use the ClaudeCode profile
export AWS_PROFILE=ClaudeCode
aws sts get-caller-identity
```

### IAM Identity Center (IDC) on headless / SSH hosts

IDC profiles (`auth_type: idc`) sign in with the browser-based device-authorization
flow. The credential process runs this automatically the first time it needs
credentials, printing a verification URL and code. On a desktop it also opens
your browser; on a headless box or over SSH it detects the lack of a local
browser (via `SSH_CONNECTION`/`SSH_TTY` or no `DISPLAY`) and instead shows a URL
you open on any other device.

**Use the `claude-bedrock` launcher instead of `claude` directly.** The installer
generates a launcher next to the binaries
(`~/claude-code-with-bedrock/claude-bedrock`, or `claude-bedrock.cmd` on Windows).
It signs you in (showing the verification URL live in your terminal — a no-op if
you already have a valid session), then runs Claude Code:

```bash
~/claude-code-with-bedrock/claude-bedrock
# First run: a verification URL + code print to your terminal.
# Open the URL on any device with a browser, approve — then Claude Code starts.

# Optional: add the folder to PATH so you can just type `claude-bedrock`:
export PATH="$HOME/claude-code-with-bedrock:$PATH"

# Use a non-default profile:
AWS_PROFILE=ClaudeCode ~/claude-code-with-bedrock/claude-bedrock
```

You can also sign in by hand without launching Claude Code (e.g. to pre-warm the
cache):

```bash
credential-process --login --profile ClaudeCode
export AWS_PROFILE=ClaudeCode
aws sts get-caller-identity
```

`--login` performs only the sign-in (it never prints credentials) and is a no-op
when a valid session is already cached. No AWS CLI is required — the
device-authorization login is built into the credential process binary, and the
SSO token is cached in `~/.aws/sso/cache/` (refreshed automatically until the
session fully expires).

> **Why a launcher instead of plain `claude`?** The IDC sign-in is interactive
> (browser approval), but Claude Code runs the credential helper
> non-interactively and cannot display its prompt reliably — so it can't be
> driven from inside a running session. If you start `claude` without an active
> sign-in, the credential process fails fast and Claude Code flashes a brief
> "Cloud authentication" error before retrying — easy to miss, leaving `claude`
> apparently stuck. The `claude-bedrock` launcher avoids this by running the
> sign-in first, in your terminal, where the URL is shown and persists.
>
> If you need to see a credential error that already scrolled away, run Claude
> Code with debug logging: `CLAUDE_CODE_DEBUG_LOGS_DIR=~/.claude/debug claude
> --debug` captures credential-resolution output to a file.

### IDC credential refresh during a session

IDC role credentials are short-lived — their lifetime is set by the IAM Identity
Center **permission set's session duration** (AWS default: 1 hour, max 12). For
IDC the generated `settings.json` wires **two** Claude Code credential hooks,
which work together:

- **`awsCredentialExport`** — the primary resolver. Its output is captured
  silently, and Claude Code re-invokes it automatically ~5 minutes before the
  credentials' `Expiration`. This drives the *silent* hourly refresh: while the
  longer-lived SSO session is still valid, the credential process re-mints role
  credentials via STS with no browser. (Requires Claude Code **v2.1.176+**;
  the credential-process JSON schema is accepted in **v2.1.181+**.)
- **`awsAuthRefresh`** (`--login`) — fires on the first credential failure and
  its output **is displayed to the user**. This is the only channel that can
  surface the sign-in message, because `awsCredentialExport` discards stderr.
  When there's no valid SSO session, this is what tells the user to relaunch
  with `claude-bedrock` instead of leaving `claude` silently retrying.

Without `awsCredentialExport`, credentials are resolved only once at startup, so
after the session duration elapses Claude Code retries expired credentials
(`API error · Retrying…`) and, on EC2, the SDK chain falls back to the instance
role. To prevent that silent wrong-identity fallback, IDC settings also set
`AWS_EC2_METADATA_DISABLED=true`, so a refresh failure surfaces as a clear
credentials error instead.

The separate ~8-hour SSO **session** expiry still requires an interactive
re-login — relaunch with `claude-bedrock`, which runs `--login` (URL shown live)
before starting Claude Code.
