# `poetry run ccwb init` — Complete Walkthrough

This document walks through every step of the interactive setup wizard, documenting each prompt, the available choices, and what each choice means for the final deployment.

Source: `source/claude_code_with_bedrock/cli/commands/init.py`

---

## Pre-Step: Profile Selection

Before the wizard begins, you must select or create a deployment profile. Profiles are stored as individual JSON files in `~/.ccwb/profiles/{name}.json`.

### First Run (No Profiles Exist)

You're prompted to name your first profile (alphanumeric + hyphens, max 64 chars). This name is used internally to track the deployment and has no effect on AWS resources.

### Subsequent Runs (Profiles Exist)

The wizard lists existing profiles and offers three choices:

| Choice | What Happens |
|--------|-------------|
| **Create new profile for different account/region** | Prompts for a new profile name, then runs the full wizard from scratch. Use this when deploying to a second AWS account or region. |
| **Update existing profile** | Lets you select a profile, then walks through all wizard steps with existing values pre-filled as defaults. Useful for changing a setting (e.g., switching models or enabling monitoring). |
| **Switch to existing profile (no changes)** | Sets the active profile and exits. No wizard steps run. Just changes which profile `ccwb deploy`, `ccwb package`, etc. operate on. |

If the selected profile already has a deployed configuration, you get a further choice:

| Choice | What Happens |
|--------|-------------|
| **View current configuration** | Displays the config summary table and exits. Read-only. |
| **Update configuration** | Runs the wizard with current values as defaults. |
| **Start fresh** | Asks for confirmation, then clears saved progress and runs the wizard from scratch. |

### Resume Support

If you previously started `ccwb init` and interrupted it (Ctrl+C), the wizard detects saved progress and offers to resume where you left off. Progress is saved after each major step completes.

---

## Prerequisites Check

Before the wizard starts gathering input, it validates your environment:

| Check | Required? | What It Validates |
|-------|-----------|-------------------|
| **AWS CLI installed** | Yes | `aws --version` succeeds |
| **AWS credentials configured** | Yes | `boto3` can call STS GetCallerIdentity |
| **Python 3.10+ available** | Yes | Python version >= 3.10 |
| **Current region** | Informational | Displays which region your AWS CLI is configured for |
| **Bedrock access** | No (optional) | Calls `bedrock:ListFoundationModels` in the current region. Failure is a warning only — the deploying administrator may not have direct Bedrock permissions. |

If any required check fails, the wizard stops.

---

## Step 1: OIDC Provider Configuration

This step configures how your users will authenticate. Everything here feeds into the CloudFormation auth stack and the credential-process binary that end users receive.

### 1a. OIDC Provider Domain

**Prompt:** `Enter your OIDC provider domain:`

**What to enter:** The domain of your identity provider. Examples:
- `company.okta.com` (Okta)
- `company.auth0.com` (Auth0)
- `login.microsoftonline.com/{tenant-id}/v2.0` (Azure AD / Entra ID)
- `my-app.auth.us-east-1.amazoncognito.com` (Cognito User Pool)
- `my-app.auth-fips.us-gov-west-1.amazoncognito.com` (Cognito GovCloud)

**Auto-detection:** The wizard parses the hostname to detect the provider type:

| Domain Pattern | Detected Provider | Auth Template Used |
|----------------|-------------------|--------------------|
| `*.okta.com` | Okta | `bedrock-auth-okta.yaml` |
| `*.auth0.com` | Auth0 | `bedrock-auth-auth0.yaml` |
| `*.microsoftonline.com` or `*.windows.net` | Azure AD | `bedrock-auth-azure.yaml` |
| `*.amazoncognito.com` or `cognito-idp.*.amazonaws.com` | Cognito | `bedrock-auth-cognito-pool.yaml` |
| Anything else | Prompts: "Is this a custom domain for AWS Cognito User Pool?" | Falls back to generic OIDC |

**Deployment impact:** The provider domain becomes the OIDC issuer URL in the IAM OIDC Provider trust policy (Direct federation) or the Cognito Identity Pool's linked provider. It determines which CloudFormation template is used and which OAuth2 endpoints the credential-process binary calls.

**GovCloud auto-correction:** If a Cognito domain is detected in a `us-gov-*` region using `.auth.` instead of `.auth-fips.`, the wizard automatically corrects it to use the FIPS endpoint.

### 1b. Cognito User Pool ID (Cognito only)

**Prompt:** `Enter your Cognito User Pool ID:` (only shown if provider type is Cognito)

**Format:** `{region}_{alphanumeric}` (e.g., `us-east-1_AbCdEfGhI`)

**Deployment impact:** Used in the CloudFormation stack parameters for `cognito-identity-pool.yaml` to link the Identity Pool to the correct User Pool. Case-sensitive.

### 1c. OIDC Client ID

**Prompt:** `Enter your OIDC Client ID:`

**Validation:** Must be at least 10 characters.

**What this is:** The application/client ID from your OIDC provider's application registration. This is the public identifier that the credential-process binary sends during the OAuth2 authorization code flow.

**Deployment impact:** Embedded into the credential-process binary's `config.json`. Also used as the `audience` parameter in IAM OIDC Provider trust policies to scope which tokens are accepted.

### 1d. Credential Storage Method

**Prompt:** `Select credential storage method:`

| Choice | Value | What It Means |
|--------|-------|---------------|
| **Keyring (Secure OS storage)** | `keyring` | Stores AWS credentials and OIDC tokens in the OS-level secure store: macOS Keychain, Windows Credential Manager, or Linux Secret Service (via `keyring` library). May prompt for a system password on some platforms. |
| **Session Files (Temporary storage)** | `session` | Stores credentials as temporary files in `~/.aws/`. Simpler but less secure — files persist until explicitly deleted or credentials expire. |

**Deployment impact:** This value is embedded in the `config.json` that ships inside the credential-process binary. It controls runtime behavior on the end user's machine, not any AWS infrastructure.

### 1e. Federation Type

**Prompt:** `Choose federation type:`

| Choice | Value | Session Duration |
|--------|-------|-----------------|
| **Direct STS** | `direct` | Up to 12 hours |
| **Cognito Identity Pool** | `cognito` | Up to 8 hours |

This choice determines how the end user's OIDC token (from their corporate login) gets converted into temporary AWS credentials. In both cases, **end users never need AWS credentials of their own** — the credential-process binary makes unauthenticated AWS API calls that accept an OIDC token and return temporary credentials. The administrator sets up the trust chain at deployment time using their AWS credentials, but after that, the admin's credentials are not involved in the runtime flow.

#### Direct STS (Recommended)

The user's credential-process binary talks directly to the AWS STS (Security Token Service):

```
User logs in via browser (Okta/Azure/etc.)
        │
        ▼
credential-process binary receives OIDC token
        │
        ├──── Calls STS:AssumeRoleWithWebIdentity ────► AWS STS
        │     (sends: OIDC token + Role ARN)                │
        │     (NO AWS credentials required —                │
        │      this API is intentionally callable           │
        │      without pre-existing credentials)            │
        │                                                   │
        │     STS validates:                                │
        │       1. IAM OIDC Provider trusts the issuer?     │
        │       2. Role trust policy allows this provider?  │
        │       3. Client ID is in the allowed audience?    │
        │                                                   │
        │◄─── Returns temporary AWS credentials ────────────┘
        │     (AccessKeyId, SecretAccessKey, SessionToken)
        │
        ▼
Claude Code uses credentials to call Bedrock
```

`AssumeRoleWithWebIdentity` is one of the few STS API calls designed to be callable without any existing AWS credentials. It exists specifically for this pattern — exchanging a trusted external identity token for temporary AWS credentials.

**What gets deployed:** `bedrock-auth-{provider}.yaml` creates:
- **IAM OIDC Provider** — tells AWS "I trust tokens issued by `company.okta.com` with client ID `xyz`"
- **IAM Role** (12-hour max session) — trust policy says "anyone presenting a valid token from this OIDC provider can assume this role via `sts:AssumeRoleWithWebIdentity`"
- **Bedrock access policy** — attached to the role, scoped to specific Bedrock actions and regions

#### Cognito Identity Pool (Legacy)

Instead of talking to STS directly, the binary talks to Cognito Identity, which acts as an intermediary:

```
User logs in via browser (Okta/Azure/etc.)
        │
        ▼
credential-process binary receives OIDC token
        │
        ├──── Calls Cognito:GetId ────────────────► Cognito Identity Pool
        │     Calls Cognito:GetCredentialsForIdentity      │
        │     (sends: OIDC token + Identity Pool ID)       │
        │     (NO AWS credentials required —               │
        │      uses signature_version=UNSIGNED)            │
        │                                                  │
        │     Cognito validates:                           │
        │       1. Is this OIDC provider linked to the     │
        │          Identity Pool?                          │
        │       2. Is the token valid?                     │
        │                                                  │
        │     Cognito internally assumes the configured    │
        │     IAM role on behalf of the user               │
        │                                                  │
        │◄─── Returns temporary AWS credentials ───────────┘
        │
        ▼
Claude Code uses credentials to call Bedrock
```

The functional result is the same — the user gets temporary AWS credentials scoped to Bedrock. The difference is that Cognito sits in the middle as a broker.

**What gets deployed:** `cognito-identity-pool.yaml` creates:
- **IAM OIDC Provider** — same trust registration as Direct
- **Cognito Identity Pool** — linked to the OIDC provider, maps authenticated users to an IAM role
- **IAM Role** (8-hour max session) — trust policy allows the Cognito Identity service principal to assume the role
- **Bedrock access policy** — same scoping as Direct

#### How to Choose

| Factor | Direct STS | Cognito Identity Pool |
|--------|-----------|----------------------|
| **Architecture** | Simpler — one fewer AWS service in the path | Extra intermediary (Cognito Identity) |
| **Session duration** | 12 hours max | 8 hours max |
| **AWS resources created** | OIDC Provider + Role | OIDC Provider + Identity Pool + Role |
| **When to use** | Default choice for new deployments | Organizations already using Cognito Identity Pools for other purposes |
| **CloudTrail attribution** | Session tags from OIDC token claims | Session tags via Cognito principal tag mappings |

#### Who needs AWS credentials?

| Person | Needs AWS credentials? | When? |
|--------|----------------------|-------|
| **Administrator** | Yes — IAM user/role with CloudFormation permissions | Only during `ccwb deploy` (setup/maintenance) |
| **End user** | No — never | N/A — they authenticate with their corporate IdP only |

The temporary AWS credentials that end users receive are created automatically by the federation flow. Users never see access keys, never configure AWS credentials, and never need an AWS account.

---

## Step 2: AWS Infrastructure Configuration

### 2a. AWS Region

**Prompt:** `Select AWS Region for infrastructure deployment (Cognito, IAM, monitoring):`

**Choices:** 17 common regions including:
- US: `us-east-1`, `us-east-2`, `us-west-1`, `us-west-2`
- GovCloud: `us-gov-west-1`, `us-gov-east-1`
- Europe: `eu-west-1`, `eu-west-2`, `eu-west-3`, `eu-central-1`
- Asia-Pacific: `ap-northeast-1`, `ap-northeast-2`, `ap-southeast-1`, `ap-southeast-2`, `ap-south-1`
- Other: `ca-central-1`, `sa-east-1`

**Default:** Your current AWS CLI region.

**Deployment impact:** This is where your CloudFormation stacks are created — the IAM OIDC Provider (or Cognito Identity Pool), monitoring infrastructure (ECS, ALB, DynamoDB), dashboards, and analytics pipeline. This is the **infrastructure region**, not the Bedrock inference region (that's configured in Step 3). IAM resources are global but the stacks themselves live in this region.

### 2b. Stack Base Name / Identity Pool Name

**Prompt:** (varies by federation type)
- Direct STS: `Stack base name (for CloudFormation):`
- Cognito: `Identity Pool Name:`

**Default:** `claude-code-auth`

**Validation:** Alphanumeric, underscores, and hyphens only.

**Deployment impact:** This name is used as the prefix for all CloudFormation stack names:

| Stack | Naming Pattern |
|-------|---------------|
| Auth stack | `{base-name}-stack` |
| Monitoring stack | `{base-name}-monitoring` |
| Dashboard stack | `{base-name}-dashboard` |
| Analytics stack | `{base-name}-analytics` |

For Cognito federation, this also becomes the literal Identity Pool name in AWS. For Direct STS, it's just a naming prefix.

---

## Step 3: Optional Features Configuration

### 3a. Monitoring and Usage Dashboards

**Prompt:** `Enable monitoring?`

**Default:** Yes

| Choice | What Gets Deployed |
|--------|-------------------|
| **Yes** | Full OpenTelemetry monitoring stack: VPC + networking, ECS Fargate cluster running the OTEL collector, Application Load Balancer for metric ingestion, CloudWatch dashboards with 19 custom Lambda widget functions, DynamoDB for metrics aggregation. The credential-process binary will be configured to send telemetry to the ALB endpoint. |
| **No** | No monitoring infrastructure. The credential-process binary won't send telemetry. You lose visibility into usage, costs, and active users. Skips all sub-questions (VPC, HTTPS, analytics, quotas). |

### 3b. VPC Configuration (if monitoring enabled)

**Prompt:** `Select VPC for monitoring infrastructure:`

| Choice | What It Means |
|--------|---------------|
| **Create new VPC** | The monitoring CloudFormation stack (`networking.yaml`) creates a dedicated VPC with public/private subnets across 2 AZs. Simplest option — fully managed lifecycle. |
| **Select existing VPC** | You pick an existing VPC and at least 2 subnets in different AZs (required for the ALB). The monitoring stack deploys into your existing network. Use this for compliance requirements or to avoid VPC quota issues. |

If you select an existing VPC, you then pick subnets (checkboxes, minimum 2 in different AZs).

### 3c. HTTPS with Custom Domain (if monitoring enabled)

**Prompt:** `Enable HTTPS with custom domain?`

**Default:** No (unless previously configured)

| Choice | What It Means |
|--------|---------------|
| **Yes** | You provide a domain name (e.g., `telemetry.company.com`) and select a Route53 hosted zone. The ALB gets an ACM certificate and a DNS record. Telemetry traffic is encrypted in transit. |
| **No** | The ALB uses HTTP only. Acceptable for internal/VPC-only deployments but not recommended for production. |

**Sub-prompts (if Yes):**
- Custom domain name (e.g., `telemetry.company.com`)
- Route53 hosted zone selection (lists zones from your account)

### 3d. Analytics Pipeline (if monitoring enabled)

**Prompt:** `Enable analytics?`

**Default:** Yes

| Choice | What Gets Deployed | Cost |
|--------|-------------------|------|
| **Yes** | Kinesis Data Firehose delivery stream, S3 data lake bucket (with Glacier lifecycle at 90 days), AWS Glue Data Catalog, Amazon Athena workgroup + pre-built query tables. Enables SQL-based historical analysis of usage data. | ~$5/month |
| **No** | No analytics pipeline. You still get real-time CloudWatch dashboards (from monitoring), but lose the ability to run ad-hoc SQL queries over historical data. |

### 3e. Quota Monitoring (if monitoring enabled)

**Prompt:** `Enable quota monitoring?`

**Default:** Yes

| Choice | What Gets Deployed |
|--------|-------------------|
| **Yes** | DynamoDB tables (`QuotaPolicies` + user metrics), Lambda quota-checking function, API Gateway endpoint for real-time quota queries. The credential-process binary will check quotas before issuing credentials. Enables per-user and per-group token limits. |
| **No** | No quota enforcement. Users have unlimited token usage (bounded only by Bedrock service quotas). |

**Sub-prompts (if Yes):**

#### Monthly Token Limit

**Prompt:** `Monthly token limit per user (in millions):`

**Default:** 225 (= 225,000,000 tokens)

The wizard auto-calculates warning thresholds:
- 80% warning: triggers an alert/notification
- 90% critical: triggers a stronger warning

**Deployment impact:** Sets the `MonthlyTokenLimit`, `WarningThreshold80`, and `WarningThreshold90` parameters in the `quota-monitoring.yaml` CloudFormation stack. These are the **default** limits; you can override per-user or per-group later with `ccwb quota set-user` / `set-group`.

#### Daily Limit (Bill Shock Protection)

**Prompt:** `Burst buffer percentage (5-25%):`

**Default:** 10%

The daily limit is calculated as: `(monthly ÷ 30) × (1 + burst%)`. The burst buffer allows day-to-day variation so users aren't blocked just because they had one busy day.

| Burst Buffer | Resulting Daily Limit (at 225M monthly) |
|-------------|---------------------------------------|
| 5% (strict) | ~7,875,000 tokens/day |
| 10% (default) | ~8,250,000 tokens/day |
| 25% (flexible) | ~9,375,000 tokens/day |

You can then override with a custom daily limit if the calculated value doesn't suit you.

#### Enforcement Modes

**Prompt:** `Daily limit enforcement:` and `Monthly limit enforcement:`

| Mode | Behavior |
|------|----------|
| **alert** (warn only) | The credential-process binary shows a browser notification warning the user, but still issues credentials. Usage data is logged. Default for daily limits. |
| **block** (deny access) | The credential-process binary refuses to issue credentials once the limit is exceeded. The user sees an error with their usage stats. Default for monthly limits. |

**Deployment impact:** These modes are stored in the quota policy and enforced by the Lambda function at credential-request time. `alert` mode is useful for rollout — you can see who would be affected before actually blocking anyone.

#### Quota Re-Check Interval

**Prompt:** `Quota check interval (minutes):`

**Default:** 30

| Value | Behavior | Tradeoff |
|-------|----------|----------|
| 0 | Check every credential request | Strictest enforcement, adds ~200ms latency to every credential refresh |
| 30 | Re-check every 30 minutes | Recommended balance of enforcement vs. performance |
| 60 | Re-check every hour | Minimal performance impact, but users can exceed limits for up to an hour before being caught |

**Deployment impact:** Embedded in the credential-process `config.json`. Controls how often the binary calls the Quota API Gateway endpoint.

---

## Additional Optional Features (outside monitoring)

### Windows Build Support

**Prompt:** `Enable Windows builds?`

**Default:** No

| Choice | What Gets Deployed |
|--------|-------------------|
| **Yes** | AWS CodeBuild project configured to compile the credential-process binary for Windows using Nuitka (a Python-to-C compiler). Also creates an S3 bucket for build artifacts and IAM roles for CodeBuild. This is needed because you can't cross-compile Windows binaries from macOS/Linux — CodeBuild runs an actual Windows build environment. |
| **No** | No Windows support. You can still build macOS and Linux binaries locally with PyInstaller. |

### Package Distribution

**Prompt:** `Distribution method:`

| Choice | What Gets Deployed | Best For |
|--------|-------------------|----------|
| **Presigned S3 URLs** | An S3 bucket for package storage and IAM resources for generating time-limited download URLs. Simple, no authentication on the download side. | Small teams (< 20 users), quick sharing |
| **Authenticated Landing Page** | An ALB + Lambda + S3 self-service portal. Users authenticate with your IdP to access a web page that auto-detects their platform and provides the correct download. | Larger teams (20-100+ users), compliance needs |
| **Disabled** | No distribution infrastructure. You'll share packages manually (zip + email, Slack, etc.). | Any size, when you have existing distribution channels |

#### Landing Page Sub-Configuration (if selected)

If you choose the landing page, additional prompts appear:

1. **IdP provider for web auth** — Which IdP authenticates users on the landing page (Okta / Azure AD / Auth0 / Cognito). This can be different from the CLI auth provider.

2. **Cognito auto-detection** — If Cognito is selected, the wizard searches for an existing Cognito User Pool stack and can auto-populate the client ID, client secret ARN, and domain.

3. **IdP domain** — The domain for web authentication (e.g., `company.okta.com`).

4. **Web application client ID** — A separate OIDC client/app registration for the web landing page (distinct from the CLI native app client ID in Step 1c).

5. **Web application client secret** — For web apps, a client secret is typically required (unlike the CLI app which uses PKCE). The wizard stores this in AWS Secrets Manager automatically.

6. **Custom domain (REQUIRED)** — ALB OIDC authentication requires HTTPS, which requires a custom domain (e.g., `downloads.company.com`).

7. **Route53 hosted zone** — For automatic DNS record creation. Optional if the domain is managed externally.

---

## Step 3 (continued): Bedrock Model Selection

### 3f. Claude Model

**Prompt:** `Select Claude model:`

Available models (as of the current codebase):

| Choice | Model ID Pattern | Available Regions |
|--------|-----------------|-------------------|
| **Claude Opus 4.1** | `us.anthropic.claude-opus-4-1-*` | US only |
| **Claude Opus 4** | `us.anthropic.claude-opus-4-*` | US only |
| **Claude Sonnet 4** | `{region}.anthropic.claude-sonnet-4-*` | US, Europe, APAC, Global |
| **Claude Sonnet 4.5** | `{region}.anthropic.claude-sonnet-4-5-*` | US, EU, Japan, Global |
| **Claude Sonnet 4.5 (GovCloud)** | `us-gov.anthropic.claude-sonnet-4-5-*` | GovCloud only |
| **Claude 3.7 Sonnet** | `{region}.anthropic.claude-3-7-sonnet-*` | US, Europe, APAC |
| **Claude 3.7 Sonnet (GovCloud)** | `us-gov.anthropic.claude-3-7-sonnet-*` | GovCloud only |

> **Note on "Claude 3.7 Sonnet":** This is Amazon Bedrock's model identifier for what Anthropic marketed as Claude 3.5 Sonnet v2. The `3-7` version number is a Bedrock naming convention, not an Anthropic release. The init wizard displays it as "Claude 3.7 Sonnet" because that matches the Bedrock model ID.

#### This is a default, not a hard restriction

The model you select here is **not enforced at the IAM level**. The deployed IAM policy grants access to all foundation models and inference profiles in the allowed regions using wildcards:

```yaml
Resource:
  - arn:${AWS::Partition}:bedrock:*::foundation-model/*
  - arn:${AWS::Partition}:bedrock:*:*:inference-profile/*
```

What this selection actually does is set **environment variables** in the `settings.json` that ships inside the user's installation package:

| Environment Variable | What It Controls | How It's Determined |
|---------------------|-----------------|---------------------|
| `ANTHROPIC_MODEL` | Claude Code's primary model for complex tasks | The model you pick in this step |
| `ANTHROPIC_SMALL_FAST_MODEL` | Claude Code's model for quick/lightweight tasks (summaries, simple edits) | Auto-calculated (see below) |

Claude Code uses two models during a session. The small/fast model is set automatically based on your primary selection:

- **If you pick Opus** → Small/Fast = Haiku 3.5 (same region prefix, e.g., `us.anthropic.claude-3-5-haiku-*`)
- **If you pick anything else** (Sonnet, Haiku) → Small/Fast = same as primary

These are configuration defaults written into `~/.claude/settings.json` on the user's machine. If a user manually edits their `settings.json` to change `ANTHROPIC_MODEL` to a different Claude model available in their allowed regions, it will work — the IAM policy does not restrict by model.

**If you need to restrict which models users can invoke**, you would need to modify the IAM policy's `Resource` field in the CloudFormation template from `foundation-model/*` to specific model ARNs. This project does not do that out of the box.

#### What this selection does affect

While it doesn't restrict model access, the model choice here does matter for two reasons:

1. **Cross-region profile availability** — different models are available in different region groupings (next prompt). Opus is US-only; Sonnet 4 has US, Europe, APAC, and Global options.
2. **IAM policy region scoping** — the cross-region profile you select in the next step determines which Bedrock regions are added to the `AllowedBedrockRegions` condition in the IAM policy. This *is* enforced — users can only call Bedrock in those specific regions.

### 3g. Cross-Region Inference Profile

**Prompt:** `Select cross-region inference profile:`

The available options depend on the model selected above. For example, Sonnet 4 offers:

| Choice | What It Means |
|--------|---------------|
| **US Cross-Region** | Requests route across `us-east-1`, `us-east-2`, `us-west-2`. Model ID prefix: `us.` |
| **Europe Cross-Region** | Requests route across `eu-central-1`, `eu-north-1`, `eu-west-1`, `eu-west-3`, etc. Model ID prefix: `eu.` |
| **APAC Cross-Region** | Requests route across `ap-northeast-1`, `ap-southeast-1`, `ap-southeast-2`, etc. Model ID prefix: `apac.` |
| **Global** | Requests route across all available regions worldwide. Model ID prefix: `global.` Best availability and lowest latency regardless of user location. |

For Opus 4/4.1, only US is available. For GovCloud Sonnet 4.5, only `us-gov` is available.

**Deployment impact:** This selection determines:
1. The **model ID prefix** (`us.`, `eu.`, `apac.`, `global.`) — different model IDs for the same model
2. The **IAM policy's allowed Bedrock regions** — the `destination_regions` list from the model config becomes the `AllowedBedrockRegions` parameter in the auth CloudFormation stack. **This is the actual enforcement boundary** — users can invoke any model, but only in these specific regions.
3. The available **source regions** for the next prompt

### 3h. Source Region

**Prompt:** `Select source region for AWS configuration:`

The choices are the `source_regions` list for the selected model + profile combination. For example, US Cross-Region Sonnet 4 offers: `us-west-2`, `us-east-2`, `us-east-1`.

**Deployment impact:** This region is written into the end user's AWS CLI configuration and Claude Code settings as the region where API calls originate. Bedrock's cross-region inference then routes the request to whichever destination region in the profile has the best availability. Choosing a source region closer to your users reduces network latency for the initial hop.

---

## Step 4: Review Configuration

The wizard displays a summary table of all settings:

```
┌─────────────────────┬──────────────────────────────────────────┐
│ Setting              │ Value                                    │
├─────────────────────┼──────────────────────────────────────────┤
│ OIDC Provider        │ company.okta.com                         │
│ OIDC Client ID       │ 0oa1b2c3d4e5f6...                       │
│ Credential Storage   │ Session Files (temporary)                │
│ Infrastructure Region│ us-east-1 (Cognito, IAM, Monitoring)     │
│ Identity Pool        │ claude-code-auth                         │
│ Monitoring           │ ✓ Enabled                                │
│ Quota Monitoring     │ ✓ Monthly: 225,000,000 (block)           │
│                      │   Daily: 8,250,000 (alert)               │
│                      │   Re-check: 30 min                       │
│ Analytics Pipeline   │ ✓ Enabled                                │
│ Monitoring VPC       │ New VPC will be created                  │
│ Claude Model         │ Claude Sonnet 4                          │
│ Bedrock Regions      │ US Cross-Region (us-east-1, us-east-2,   │
│                      │ us-west-2)                               │
│ AWS Account          │ 123456789012                             │
└─────────────────────┴──────────────────────────────────────────┘
```

It then lists all AWS resources that will be created when you run `ccwb deploy`:

- IAM OIDC Provider or Cognito Identity Pool
- IAM roles and policies for Bedrock access
- (If monitoring) CloudWatch dashboards, OTEL collector, ECS cluster, ALB
- (If analytics) Kinesis Firehose, S3 bucket, Glue catalog, Athena tables
- (If quotas) DynamoDB tables, Lambda function, API Gateway
- (If CodeBuild) CodeBuild project, S3 artifact bucket
- (If distribution) S3 bucket + presigned URL infra, or ALB + Lambda landing page

---

## After Init Completes

The wizard saves the configuration to `~/.ccwb/profiles/{name}.json` and displays next steps:

```
1. Deploy infrastructure:  poetry run ccwb deploy
2. Create package:         poetry run ccwb package
3. Test authentication:    poetry run ccwb test
4. View profile:           poetry run ccwb context show {name}
```

**No AWS resources are created during `ccwb init`.** It only generates and saves a configuration file. The actual CloudFormation deployments happen when you run `ccwb deploy`.
