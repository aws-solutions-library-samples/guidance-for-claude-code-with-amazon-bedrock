# IAM Identity Center Setup Guide for Amazon Bedrock

This guide walks you through configuring AWS IAM Identity Center (formerly AWS SSO) as the authentication method for Claude Code with Amazon Bedrock.

## Table of Contents

1. [When to use IAM Identity Center instead of Direct IdP](#1-when-to-use-iam-identity-center-instead-of-direct-idp)
2. [What is NOT supported on this path](#2-what-is-not-supported-on-this-path)
3. [Prerequisites](#3-prerequisites)
4. [Deploy the CloudFormation stack](#4-deploy-the-cloudformation-stack)
5. [Run `ccwb init`](#5-run-ccwb-init)
6. [First login](#6-first-login)
7. [Extending sessions to 7 days](#7-extending-sessions-to-7-days)
8. [Per-user cost attribution](#8-per-user-cost-attribution)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. When to use IAM Identity Center instead of Direct IdP

Consider IAM Identity Center when:

- **Azure AD conditional access** is configured to shorten OIDC tokens below what this repo can work with (tokens shorter than 1 hour cause frequent re-authentication with the Direct IdP path).
- **Corporate VPN or proxy** blocks `localhost:8400` — the OIDC callback port used by the Direct IdP credential provider.
- **Team is already on IAM IDC + on-prem AD** and does not want to create separate OIDC application registrations in Okta or Azure AD.
- **Sessions longer than 1 hour without browser re-prompts** — IAM Identity Center portal sessions can be configured up to 90 days (168 hours is the recommended 7-day setting). Once logged in, users do not see a browser popup again until the portal session expires.
- **Smaller teams** where a full OIDC IdP deployment isn't justified.

### Comparison

| Feature | Direct IdP (OIDC) | IAM Identity Center |
|---------|-------------------|---------------------|
| Session length (no re-auth) | Refresh token lifetime (hours–days) | Portal session: up to 90 days |
| Credential refresh | Silent (PKCE refresh token) | Silent (AWS SDK + sso cache) |
| Quota enforcement | ✅ Full (`_check_quota()`) | ❌ Not available (no OIDC token) |
| User identity attribution | ✅ Email, department, groups from JWT | ✅ Email + permission set (from ARN) |
| External IdP required | ✅ Yes | ❌ No (uses AWS-native identity) |
| Setup complexity | Medium (OIDC app registration) | Low (AWS console only) |

---

## 2. What is NOT supported on this path

Be aware of these limitations before choosing IAM Identity Center:

### OIDC quota enforcement not available

The `_check_quota()` function in the credential provider requires an OIDC ID token in the `Authorization` header to identify the caller. IAM Identity Center does not produce an OIDC ID token accessible to this repo — users authenticate through the IDC portal, not an OIDC client registered in this deployment.

**Impact:** Per-user token quota limits (the `ccwb quota` feature) **cannot be enforced** on the IDC path. Quota configuration fields will be ignored.

**Workaround:** Use AWS Service Control Policies (SCPs) or IAM conditions to enforce limits at the AWS level.

### OpenTelemetry attribution is ARN-based, not claim-based

On the OIDC path, user attributes (email, department, cost centre, manager) are extracted directly from JWT claims, giving rich attribution in the observability dashboard.

On the IDC path, user identity is extracted by parsing the caller's assumed-role ARN in `otel_helper/__main__.py`. For IAM Identity Center users, the ARN pattern is:

```
arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_BedrockDeveloperAccess_abc123/alice@company.com
```

The parser extracts `alice@company.com` as the email and `BedrockDeveloperAccess` as the permission set name. This provides **basic attribution** (email and permission set), but department, team, and cost centre claims are not available unless configured separately through IAM Identity Center attributes (see [Per-user cost attribution](#8-per-user-cost-attribution)).

### Cost attribution via session tags requires manual IAM IDC configuration

See [Section 8](#8-per-user-cost-attribution) for the manual steps to enable cost tags.

---

## 3. Prerequisites

Before starting:

- **IAM Identity Center is deployed** in your AWS organisation (management account) and at least one member account is enrolled.
- **Developer machines have AWS CLI v2** installed (version 2.9+ for SSO session support). This is separate from the `credential_provider` binary packaged with this repo.
- **Users have been (or will be) assigned** to an IAM IDC permission set in the target account. You will create the permission set as part of this guide.
- **You have access to the target AWS account** where Bedrock will be called (does not need to be the management account).

---

## 4. Deploy the CloudFormation stack

The `bedrock-auth-idc.yaml` template creates:
- A customer-managed IAM policy (`BedrockIDCFederatedRole-BedrockPolicy`) with Bedrock permissions.
- An IAM role (`BedrockIDCFederatedRole` by default) that IDC-authenticated users can assume via role chaining.

### Option A: Using `ccwb deploy` (recommended)

After completing `ccwb init` with the **AWS IAM Identity Center** option:

```bash
poetry run ccwb deploy auth
```

The deploy command will automatically select `bedrock-auth-idc.yaml` and pass your configured parameters.

### Option B: AWS Console

1. Open **CloudFormation → Create stack → With new resources**.
2. Upload `deployment/infrastructure/bedrock-auth-idc.yaml`.
3. Parameters:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `FederatedRoleName` | Name for the IAM role | `BedrockDeveloperAccess` |
| `IdentityPoolName` | Logical name prefix | `claude-code-idc` |
| `AllowedBedrockRegions` | Comma-separated regions | `us-east-1,us-west-2` |
| `EnableMonitoring` | CloudWatch metrics | `true` |

4. On the **Review** page, check **I acknowledge that AWS CloudFormation might create IAM resources with custom names**.
5. Click **Create stack**.

### Attach the policy to your Permission Set

The CloudFormation stack outputs a `BedrockPolicyArn`. To allow users direct Bedrock access (without role chaining), attach this policy to your IAM Identity Center Permission Set:

1. Open **IAM Identity Center → Permission sets → [your permission set]**.
2. Click **Add policies** → **Customer managed**.
3. Search for the policy named `BedrockIDCFederatedRole-BedrockPolicy` (or your custom name).
4. Click **Attach**.
5. Re-provision the permission set to affected accounts:
   **IAM Identity Center → AWS accounts → [account] → Reprovision**.

> **Note:** If you prefer role chaining (the IDC role assumes the Bedrock role), skip the policy attachment step and configure `role_arn` in `~/.aws/config` as shown in [Section 5](#5-run-ccwb-init).

---

## 5. Run `ccwb init`

```bash
poetry run ccwb init
```

When prompted for **Authentication method**, select:

```
> AWS IAM Identity Center (SSO)
```

You will be asked for:

| Prompt | Description | Example |
|--------|-------------|---------|
| IAM Identity Center start URL | Your organisation's SSO portal URL | `https://your-company.awsapps.com/start` |
| AWS region for IAM Identity Center | The region where your IDC instance is deployed | `us-east-1` |
| AWS Account ID | 12-digit account ID for the target account | `123456789012` |
| Permission set / role name | The Permission Set assigned to developers | `BedrockDeveloperAccess` |

The wizard generates and optionally writes the following `~/.aws/config` block:

```ini
[profile ClaudeCode]
sso_session    = your-company
sso_account_id = 123456789012
sso_role_name  = BedrockDeveloperAccess
region         = us-east-1

[sso-session your-company]
sso_start_url          = https://your-company.awsapps.com/start
sso_region             = us-east-1
sso_registration_scopes = sso:account:access
```

If you are using role chaining (Bedrock role separate from your base IDC role), add these lines to the `[profile ClaudeCode]` section:

```ini
role_arn          = arn:aws:iam::123456789012:role/BedrockIDCFederatedRole
role_session_name = ClaudeCode
```

---

## 6. First login

After running `ccwb init`, log in once:

```bash
aws sso login --profile ClaudeCode
```

This opens a browser window to the IAM Identity Center portal. After you approve the request, a portal session token is cached at `~/.aws/sso/cache/`. From this point:

- The AWS SDK automatically uses the cached token to obtain short-lived IAM credentials (up to 12 hours).
- When the short-lived credentials expire, they are refreshed silently — **no browser popup**.
- The browser popup only reappears when the **portal session** expires (configurable — see [Section 7](#7-extending-sessions-to-7-days)).

### Verify the profile works

```bash
aws sts get-caller-identity --profile ClaudeCode
```

The response should show your account ID and an assumed-role ARN like:

```json
{
  "UserId": "AROAEXAMPLEID:alice@company.com",
  "Account": "123456789012",
  "Arn": "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_BedrockDeveloperAccess_abc123/alice@company.com"
}
```

---

## 7. Extending sessions to 7 days

AWS role credentials (`AWS_ACCESS_KEY_ID` etc.) are always short-lived — maximum 12 hours. This is an AWS hard limit that cannot be changed.

What determines whether the user sees a browser popup is the **IAM Identity Center portal session duration**, not the credential duration. After `aws sso login`, a portal session token is stored in `~/.aws/sso/cache/`. As long as this token is valid, the AWS SDK silently gets new 12-hour credentials without any user interaction.

Configure the portal session to 7 days (168 hours) and users log in once per week.

### Step 1 — Set portal session duration in IAM Identity Center

```
AWS Console → IAM Identity Center → Settings → Authentication
→ Session management → Access portal session duration → 168 hours (7 days)
```

> **Maximum:** 90 days (2,160 hours) — AWS hard limit for portal session duration.

### Step 2 — Match the upstream IdP session policy (if IDC is federated)

If your IAM Identity Center is federated with an external IdP, the upstream IdP controls the maximum session length. The IDC portal session **cannot exceed** the upstream identity session.

#### If IDC is federated with Okta

```
Okta Admin Console → Applications → [AWS IAM Identity Center app] → Sign On
→ Session lifetime: 10,080 minutes (7 days)
→ Session max lifetime: 10,080 minutes (7 days)
```

#### If IDC is federated with on-prem Active Directory via AD FS

```
AD FS Management → Relying Party Trusts → [AWS IAM Identity Center] → Properties
→ Monitoring tab — confirm token lifetime is ≥ 168 hours
```

Or via PowerShell:

```powershell
Set-AdfsRelyingPartyTrust -TargetName "AWS IAM Identity Center" -TokenLifetime 10080
```

#### If IDC uses its own directory (no upstream federation)

No additional configuration needed — the portal session duration set in Step 1 applies directly.

### Step 3 — Verify the portal session expiry

After `aws sso login`:

```bash
# Find the cached portal token
cat ~/.aws/sso/cache/*.json | python3 -m json.tool
```

Look for `"expiresAt"` — it should be approximately 7 days from the current time if your configuration is correct:

```json
{
  "startUrl": "https://your-company.awsapps.com/start",
  "region": "us-east-1",
  "accessToken": "...",
  "expiresAt": "2026-04-30T12:00:00UTC"
}
```

If `expiresAt` is only 1 hour in the future, the portal session duration has not been updated — revisit Step 1 and Step 2.

---

## 8. Per-user cost attribution

By default, Bedrock API calls are attributed to the IAM role (the permission set role), not to individual users. To attribute costs to individual users:

### Enable user attributes in IAM Identity Center

1. Open **IAM Identity Center → Settings → Attributes for access control**.
2. Click **Enable** → **Configure attributes**.
3. Add this attribute mapping:

   | Key | Value |
   |-----|-------|
   | `userName` | `${user:email}` |

4. Click **Save changes**.

### Enable the cost allocation tag in AWS Billing

1. Open **AWS Billing → Cost allocation tags**.
2. Search for `userName`.
3. Select the tag and click **Activate**.

> **Note:** Cost allocation tags take up to 24 hours to appear in Cost Explorer after activation.

### Session tag propagation

When IAM Identity Center assumes roles with Attributes for Access Control enabled, the `userName` attribute is passed as an `aws:PrincipalTag/userName` session tag. Cost Explorer reports this tag once it is activated.

---

## 9. Troubleshooting

### "Error loading SSO Token" or "Token is expired"

The portal session has expired. Re-login:

```bash
aws sso login --profile ClaudeCode
```

This is different from credential expiry. Check the cache:

```bash
cat ~/.aws/sso/cache/*.json | python3 -c "import sys,json; [print(k,v) for d in [json.load(open(f)) for f in __import__('glob').glob(sys.argv[1])] for k,v in d.items() if k=='expiresAt']" ~/.aws/sso/cache/*.json
```

### "aws sso login" opens the wrong browser profile

Set the `AWS_DEFAULT_BROWSER` environment variable or use the `--browser` flag:

```bash
AWS_DEFAULT_BROWSER=/usr/bin/google-chrome aws sso login --profile ClaudeCode
```

On macOS, to open in a specific Chrome profile, use a custom browser script.

### Permission set not visible to user

Check that the user is assigned to the permission set in the correct account:

```
IAM Identity Center → AWS accounts → [account] → Users and groups
```

The permission set must be provisioned after assignment. Click **Reprovision** if the role does not appear.

### Session duration not taking effect (Okta override)

If the portal session duration is still 1 hour after updating IAM IDC settings, the upstream Okta app policy may be overriding it. Check:

```
Okta Admin Console → Applications → [AWS IAM Identity Center app] → Sign On
→ Session lifetime (currently configured value)
```

The Okta session lifetime must be ≥ the IAM IDC portal session duration. If Okta is set to 60 minutes, IDC sessions cannot exceed 60 minutes regardless of the IDC setting.

### "An error occurred (AccessDenied)" when calling Bedrock

Verify the Bedrock policy is attached to the permission set:

```bash
aws iam list-attached-role-policies \
  --role-name AWSReservedSSO_BedrockDeveloperAccess_$(aws iam list-roles --query "Roles[?starts_with(RoleName,'AWSReservedSSO_BedrockDeveloperAccess_')].RoleName | [0]" --output text | cut -d'_' -f4) \
  --profile ClaudeCode
```

Or simply check if you can list foundation models:

```bash
aws bedrock list-foundation-models --region us-east-1 --profile ClaudeCode
```

---

## Next Steps

Once you've completed this setup:

1. Deploy infrastructure: `poetry run ccwb deploy`
2. Create distribution package: `poetry run ccwb package`
3. Test authentication: `poetry run ccwb test`
4. Distribute the `dist/` folder to your users

For more information:

- [Token and Session Management](../TOKEN_AND_SESSION_MANAGEMENT.md)
- [Monitoring and Observability](../MONITORING.md)
- [Quota Monitoring](../QUOTA_MONITORING.md) — note: quota enforcement is not available on the IDC path
