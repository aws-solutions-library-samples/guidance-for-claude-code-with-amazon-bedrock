# IAM Identity Center Setup

This guide covers deploying Claude Code with Amazon Bedrock using **AWS IAM Identity Center** (formerly AWS SSO) instead of an external OIDC identity provider.

## When to Use This Path

Choose IAM Identity Center when:
- Your organization already uses IAM Identity Center for AWS access
- You don't want to configure an external IdP (Okta, Azure AD, Auth0, etc.)
- Users already run `aws sso login` as part of their workflow
- You want the simplest possible auth setup

Choose the OIDC path instead when:
- You need fine-grained group-based quota policies from JWT claims
- Your IdP provides rich user attributes (department, team, cost center)
- You need the browser-based auth flow for users without AWS CLI access

## Prerequisites

1. **IAM Identity Center** configured in your AWS account
2. **Permission set** granting Bedrock access (see [Permission Set Setup](#permission-set-setup) below)
3. **Session name = email**: IAM Identity Center must use the user's email as the session name (this is the default)
4. **AWS CLI v2** installed on developer machines

## How It Works

```
Developer machine:
  aws sso login → SSO credentials cached locally
  → credential-process detects sso_enabled=false
  → passes through ambient AWS credentials (no OIDC browser flow)
  → user identified by IAM ARN session name (email)

Server side:
  API Gateway receives SigV4-signed request
  → validates IAM credentials
  → Lambda extracts email from ARN: .../AWSReservedSSO_.../user@company.com
  → quota enforced per user
```

## Setup

### 1. Permission Set Setup

Create a permission set in IAM Identity Center that grants Bedrock access:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream",
        "bedrock:ListFoundationModels",
        "bedrock:ListInferenceProfiles"
      ],
      "Resource": "*"
    }
  ]
}
```

Assign this permission set to the users/groups who need Claude Code access.

### 2. Initialize with SSO Disabled

```bash
poetry run ccwb init
```

When prompted for SSO authentication, select **No**:

```
? Enable SSO authentication (OIDC)? No
```

This sets `sso_enabled: false` in your profile. The system will use ambient AWS credentials instead of the OIDC browser flow.

### 3. Configure AWS CLI SSO Profile

Each developer needs an AWS CLI SSO profile. Example `~/.aws/config`:

```ini
[profile claude-bedrock]
sso_session = my-org
sso_account_id = 123456789012
sso_role_name = BedrockAccess

[sso-session my-org]
sso_start_url = https://my-org.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access
```

### 4. Deploy

```bash
poetry run ccwb deploy
```

The auth stack is skipped (no OIDC). Monitoring, dashboard, and quota stacks deploy normally.

### 5. Package for Users

```bash
poetry run ccwb package
```

The generated package includes the credential-process binary configured for passthrough mode. Users authenticate with `aws sso login` and the credential-process surfaces their ambient credentials to Claude Code.

## User Workflow

```bash
# One-time: login to AWS SSO
aws sso login --profile claude-bedrock

# Use Claude Code normally — credentials are automatic
claude
```

Re-authentication is needed when the SSO session expires (typically 8-12 hours, configurable in IAM Identity Center).

## Quota Enforcement

Quota enforcement works differently for IDC users compared to OIDC:

| Aspect | OIDC Path | IDC Path |
|---|---|---|
| Authentication | JWT Bearer token | SigV4-signed request |
| User identity | JWT `email` claim | ARN session name |
| API Gateway auth | JWT Authorizer | AWS_IAM |
| Group membership | JWT `groups` claim | Not available (user-level only) |

### How Email Is Resolved

IAM Identity Center uses the user's email as the role session name by default. The assumed-role ARN looks like:

```
arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_BedrockAccess_abc123/alice@company.com
```

The quota Lambda extracts `alice@company.com` from the last segment after `/`.

### Requirements for Quota to Work

1. **Email as session name**: This is the IAM Identity Center default. If your org has customized session names, quota enforcement won't resolve the user identity.
2. **`quota_api_endpoint`** in config.json: The package must include the API Gateway endpoint.
3. **`execute-api:Invoke` permission**: The user's IAM role must be able to invoke the quota API. Add to the permission set if not already included:

```json
{
  "Sid": "QuotaCheckAccess",
  "Effect": "Allow",
  "Action": "execute-api:Invoke",
  "Resource": "arn:aws:execute-api:*:*:*/*/GET/check"
}
```

### Limitations (IDC-specific)

- **No group-based policies**: JWT group claims aren't available — only user-level and default policies apply
- **Email format required**: Session name must contain `@` to be recognized as an email
- **No Cowork 3P support**: Claude Desktop (Cowork) requires the OIDC flow — IDC is CLI-only

## Monitoring and OTEL

| Feature | IDC Support |
|---|---|
| Central collector (ALB + ECS) | ✅ Works — otel-helper resolves identity from monitoring token |
| Sidecar collector (local) | ✅ Works — exports directly to CloudWatch |
| Per-user dashboard attribution | ⚠️ Requires monitoring token — works if credential-process can issue one |
| ALB JWT validation | ❌ Not applicable — IDC users don't have JWTs for OTEL |

For IDC deployments using the central collector with HTTPS, configure the ALB **without** `OidcIssuerUrl` (deploy with `sso_enabled=false`) so JWT validation is disabled. Telemetry flows through without auth at the ALB level, secured by security groups instead.

## Comparison: OIDC vs IDC

| Feature | OIDC | IDC |
|---|---|---|
| External IdP required | ✅ Yes | ❌ No |
| Browser popup for auth | ✅ Every 1-24h | ❌ Never (CLI only) |
| Cowork 3P (Claude Desktop) | ✅ Supported | ❌ Not supported |
| Group-based quota | ✅ From JWT claims | ❌ User-level only |
| Rich user attributes | ✅ From JWT (dept, team, etc.) | ⚠️ Email only (from ARN) |
| Setup complexity | Medium (IdP config) | Low (permission set only) |
| Credential refresh | Automatic (refresh_token) | `aws sso login` when expired |
