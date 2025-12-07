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

### No-Browser Authentication Mode

For headless servers, SSH sessions, or environments where opening a browser is not practical, the credential process supports device code flow (RFC 8628):

```bash
# Test authentication without opening a browser
~/claude-code-with-bedrock/credential-process --no-browser
```

Instead of opening a browser automatically, you'll see instructions like:

```
======================================================================
  Azure AD Authentication - No Browser Mode
======================================================================

  1. Visit: https://microsoft.com/devicelogin
  2. Enter code: ABCD-1234

  Code expires in 15 minutes
======================================================================

Waiting for authentication to complete...
```

You can complete authentication on any device (phone, laptop, etc.) by visiting the URL and entering the code. The CLI polls for completion and continues once you approve the authentication.

**Provider Support:**
- ✅ Okta - Full support
- ✅ Azure AD - Full support
- ✅ Auth0 - Full support
- ❌ Cognito User Pools - Not supported (use browser mode)

**Configuration:**
You can enable no-browser mode permanently by adding it to the config:

```json
{
  "profiles": {
    "YourProfile": {
      "no_browser_mode": true,
      ...
    }
  }
}
```

Or use the `--no-browser` flag to override on a per-invocation basis.

Credentials are cached after the first authentication. Test this by making successive calls:

```bash
# First call - includes authentication
time aws sts get-caller-identity --profile ClaudeCode

# Second call - uses cached credentials
time aws sts get-caller-identity --profile ClaudeCode
```

The first call takes 3-10 seconds including authentication. Cached calls complete in under a second. Credentials remain valid for up to 8 hours.

## Credential Process CLI Reference

The credential-process binary supports several command-line options for testing and troubleshooting:

```bash
~/claude-code-with-bedrock/credential-process [OPTIONS]
```

**Available Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--profile NAME` | `-p` | Configuration profile to use (default: "ClaudeCode") |
| `--version` | `-v` | Show program version and exit |
| `--clear-cache` | | Clear cached credentials and force re-authentication |
| `--check-expiration` | | Check if credentials need refresh (exit 0 if valid, 1 if expired) |
| `--refresh-if-needed` | | Refresh credentials if expired (useful for cron jobs) |
| `--no-browser` | | Use device code flow instead of opening a browser (for headless/SSH environments) |
| `--get-monitoring-token` | | Get cached monitoring token instead of AWS credentials |
| `--help` | `-h` | Show help message and exit |

**Usage Examples:**

```bash
# Force re-authentication
~/claude-code-with-bedrock/credential-process --clear-cache

# Check if credentials are still valid
~/claude-code-with-bedrock/credential-process --check-expiration
if [ $? -eq 0 ]; then
    echo "Credentials are valid"
else
    echo "Credentials expired"
fi

# Use device code flow (no browser)
~/claude-code-with-bedrock/credential-process --no-browser

# Use a different profile
~/claude-code-with-bedrock/credential-process --profile MyProfile

# Get monitoring token for debugging
~/claude-code-with-bedrock/credential-process --get-monitoring-token
```

**Environment Variables:**

- `CCWB_PROFILE` - Override the default profile name
- `COGNITO_AUTH_DEBUG` - Enable debug logging (set to "1", "true", or "yes")

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
