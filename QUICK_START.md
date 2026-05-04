# Quick Start Guide

Complete deployment walkthrough for IT administrators deploying Claude Code with Amazon Bedrock.

**Time Required:** 2-3 hours for initial deployment
**Skill Level:** AWS administrator with IAM/CloudFormation experience

---

## Prerequisites

### Software Requirements

- Python 3.10-3.13
- Poetry (dependency management)
- AWS CLI v2
- Git

**macOS admins — check your machine architecture before building:**

```bash
uname -m
```

| Output | Your Mac | Builds natively |
|--------|----------|----------------|
| `arm64` | Apple Silicon (M1/M2/M3/M4) | `macos-arm64` — Intel requires [optional setup](assets/docs/CLI_REFERENCE.md#intel-mac-build-setup-optional) |
| `x86_64` | Intel Mac | `macos-intel` — cannot build `macos-arm64` |

> Intel (`macos-intel`) binaries run on both Intel and Apple Silicon Macs (via Rosetta). ARM64 binaries only run on Apple Silicon. If your developers have a **mixed fleet**, build `macos-intel` — it covers everyone.

### AWS Requirements

- AWS account with appropriate IAM permissions to create:
  - CloudFormation stacks
  - IAM OIDC Providers or Cognito Identity Pools
  - IAM roles and policies
  - (Optional) Amazon Elastic Container Service (Amazon ECS) tasks and Amazon CloudWatch dashboards
  - (Optional) Amazon Athena, AWS Glue, AWS Lambda, and Amazon Data Firehose resources
  - (Optional) AWS CodeBuild
- Amazon Bedrock activated in target regions

### OIDC Provider Requirements

This guide covers the **AWS infrastructure** side of the deployment. It assumes you have already configured your identity provider (IdP). **You must complete your IdP setup before running `ccwb init`** — the wizard will ask for your provider domain and client ID, and will fail without them.


| Your IdP | Setup guide |
|---|---|
| **Okta** | [Okta Setup Guide](assets/docs/providers/okta-setup.md) |
| **Microsoft Entra ID (Azure AD)** | [Microsoft Entra ID Setup Guide](assets/docs/providers/microsoft-entra-id-setup.md) |
| **Auth0** | [Auth0 Setup Guide](assets/docs/providers/auth0-setup.md) |
| **AWS Cognito User Pool** | [Cognito User Pool Setup Guide](assets/docs/providers/cognito-user-pool-setup.md) |

Each guide walks through creating the application, setting the redirect URI to `http://localhost:8400/callback`, enabling PKCE, and noting the two values you will need here: your **provider domain** and **client ID**.

Once your IdP application is created and you have those two values, return here and continue from Step 1.



### Supported AWS Regions

The guidance can be deployed in any AWS region that supports:

- IAM OIDC Providers or Amazon Cognito Identity Pools
- Amazon Bedrock
- (Optional) Amazon Elastic Container Service (Amazon ECS) tasks and Amazon CloudWatch dashboards
- (Optional) Amazon Athena, AWS Glue, AWS Lambda, and Amazon Data Firehose resources
- (Optional) AWS CodeBuild

### Cross-Region Inference

Claude Code uses Amazon Bedrock's cross-region inference for optimal performance and availability. During setup, you can:

- Select your preferred Claude model (Opus, Sonnet, Haiku)
- Choose a cross-region profile (US, Europe, APAC) for optimal regional routing
- Select a specific source region within your profile for model inference

This automatically routes requests across multiple AWS regions to ensure the best response times and highest availability. Modern Claude models (3.7+) require cross-region inference for access.

---

## Deployment Steps

### Step 1: Clone Repository and Install Dependencies

```bash
# Clone the repository
git clone https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock
cd guidance-for-claude-code-with-amazon-bedrock/source

# Install dependencies
poetry install
```

### Step 2: Initialize Configuration

Run the interactive setup wizard:

```bash
poetry run ccwb init
```

The wizard runs through three numbered steps plus optional features. Every question is explained below — read this section before running the wizard so you know exactly what to enter.

> **Before you run `ccwb init`:** The wizard calls AWS APIs to validate account id ( using your **administrator** credentials — not developer credentials). Make sure your terminal has a valid AWS session before you start. See [How ccwb init reads your AWS credentials](#how-ccwb-init-reads-your-aws-credentials) below.

---

#### Complete Wizard Flow — Decision Tree

Use this to quickly see which questions apply to your setup:

```
ccwb init
│
├── Profile name → e.g. "CorpIT-Prod"
│
├── STEP 1: Enable SSO authentication? (Y/n)
│   │
│   ├── Yes (default) ──────────────────────────────────────────────┐
│   │                                                                │
│   │   Provider domain? (e.g. company.okta.com)                    │
│   │   Client ID?                                                   │
│   │   │                                                            │
│   │   ├── Azure detected?                                          │
│   │   │   └── Auth mode: Public / Secret / Certificate             │
│   │   │       ├── Secret → enter client secret (stored in keyring) │
│   │   │       └── Certificate → cert path + key path               │
│   │   │                                                            │
│   │   ├── Credential storage: Keyring / Session Files              │
│   │   └── Federation type: Direct STS / Cognito Identity Pool      │
│   │                                                                │
│   └── No → skips all auth questions, goes to Step 2 ─────────────┘
│
├── STEP 2: AWS Infrastructure
│   ├── AWS region? (where CloudFormation stacks are deployed)
│   └── Stack base name? (prefix for all stack names)
│
├── OPTIONAL FEATURES
│   │
│   ├── Enable monitoring?
│   │   ├── No → skip to Windows builds
│   │   └── Yes
│   │       ├── VPC: Create new / Use existing
│   │       │   └── Existing → enter VPC ID + subnet IDs
│   │       ├── Enable HTTPS with custom domain?
│   │       │   ├── No → use HTTP (plain text endpoint)
│   │       │   └── Yes → domain name + Route53 hosted zone
│   │       ├── Enable analytics? (Athena + S3 data lake)
│   │       └── Enable quota monitoring?
│   │           └── Yes
│   │               ├── Monthly token limit (millions)
│   │               ├── Burst buffer % (5-25)
│   │               ├── Custom daily limit (optional)
│   │               ├── Daily enforcement: alert / block
│   │               ├── Monthly enforcement: alert / block
│   │               └── Quota re-check interval (minutes)
│   │
│   ├── Enable Windows builds? (CodeBuild)
│   ├── Generate CoWork 3P MDM config?
│   └── Distribution method?
│       ├── Presigned S3 URLs
│       ├── Authenticated Landing Page
│       │   ├── IdP provider + domain + client ID
│       │   ├── Custom domain (e.g. downloads.company.com)
│       │   └── Route53 hosted zone
│       └── Disabled
│
└── STEP 3: Bedrock Model Selection
    ├── Select Claude model (Sonnet / Haiku / Opus)
    ├── Cross-region inference profile (US / EU / APAC / Global)
    └── Source region (e.g. us-east-1)
```

---

#### Profile Name

**Q: `Enter a name for this profile:`**

The very first thing the wizard asks is a profile name. A **profile** is a named configuration set stored in `~/.ccwb/profiles/<name>.json`. It contains everything about one deployment: auth type, IdP domain, AWS region, stack names, monitoring settings, and model selection.

**Why profiles matter:**
- You run `ccwb init` once per deployment environment, not once per machine.
- Each profile maps to one set of AWS CloudFormation stacks.
- You can have multiple profiles on the same machine — for example `prod` and `staging`, or `us-prod` and `eu-prod` for regional deployments.

**Naming rules:** lowercase letters, numbers, and hyphens only. Good examples: `prod`, `corp-it-prod`, `us-bedrock-dev`.

**Profile commands:**
```bash
ccwb context list          # see all profiles
ccwb context use <name>    # switch active profile
ccwb context show          # view active profile details
```

Nothing is deployed to AWS when you run `ccwb init` — the profile is only saved locally. Deployment happens in Step 3.

---

#### How ccwb init reads your AWS credentials

`ccwb init` itself (the wizard running on your administrator machine) needs AWS credentials to call AWS APIs to validate that your account ID is reachable.

boto3 (the AWS SDK used internally) resolves credentials in this order — **first source that provides a valid, non-expired credential wins**:

| Priority | Source | How to set it |
|---|---|---|
| **1 — highest** | Environment variables | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` (+ optional `AWS_SESSION_TOKEN`) |
| **2** | `~/.aws/credentials` file | `[default]` or named profile via `AWS_PROFILE` |
| **3** | `~/.aws/config` file | SSO profiles (`aws sso login`), `credential_process` entries, assumed-role profiles |
| **4** | IAM instance profile | Automatic on EC2 — no config needed |
| **5 — lowest** | ECS container role | Automatic on ECS tasks — no config needed |

**Common issue: stale environment variables override everything.** If you ran `aws sts assume-role` earlier and those vars are still exported, boto3 will try them first — even if they are expired — and will not fall back to your credential file. If `ccwb init` fails with an AWS credentials error but `aws sts get-caller-identity` works from a fresh shell, see [Troubleshooting](#ccwb-init-fails-aws-credentials-configured-even-though-aws-sts-get-caller-identity-works) below.

**Recommended for most administrators:**
```bash
# SSO login (if your org uses IAM Identity Center)
aws sso login --profile <your-admin-profile>
export AWS_PROFILE=<your-admin-profile>

# Verify before starting
aws sts get-caller-identity

# Then run the wizard
poetry run ccwb init
```

---

#### Step 1: Authentication Configuration

**What it asks:** `Enable SSO authentication? (Y/n)`

Choose whether developers will authenticate through an OIDC identity provider to reach Bedrock:

| Answer | When to use |
|---|---|
| **Yes** (default) | You have Okta, Azure AD, Auth0, or Cognito User Pool — full per-user attribution and quota enforcement |
| **No** | Analytics-only deployment, or developers already have IAM/role access to Bedrock |

> **Note:** AWS IAM Identity Center (SSO) support is coming in a future release. If your org uses AWS SSO today, choose **No** and configure developer access via your existing IAM Identity Center setup outside this tool.

---

##### If you answered Yes (SSO enabled)

**Q: `Enter your OIDC provider domain:`**

Enter the domain of your identity provider — the base URL without `https://`:

| Provider | Example value |
|---|---|
| Okta | `company.okta.com` |
| Microsoft Entra ID | `login.microsoftonline.com/{your-tenant-id}/v2.0` |
| Auth0 | `company.auth0.com` |
| Cognito User Pool | `my-app.auth.us-east-1.amazoncognito.com` |

The wizard auto-detects the provider type from the domain for the four known providers above. If it detects Cognito, it will also ask for your **User Pool ID** (case-sensitive, format: `us-east-1_XXXXXXXXX`).

> **Custom or non-standard OIDC domains** (e.g. Keycloak, PingFederate, Okta vanity domains like `sso.mycompany.com`): the wizard cannot auto-detect the type and will prompt you to select manually:
> ```
> Could not auto-detect provider type from domain.
> Select your identity provider type:
>   > Okta (or generic OIDC)
>     Microsoft Entra ID / Azure AD
>     Auth0
>     AWS Cognito User Pool
> ```
> Choose **Okta (or generic OIDC)** for any standard OIDC provider not listed (Keycloak, PingFederate, ADFS, etc.) — it uses the most compatible CloudFormation template.

---

**Q: `Enter your OIDC Client ID:`**

The Application (client) ID from your IdP app registration. You noted this during the IdP setup in Step 0.

- Okta: found in Applications → your app → General tab
- Azure: found in App registrations → your app → Overview → Application (client) ID
- Auth0: found in Applications → your app → Settings → Client ID

---

**Q (Azure only): `Select authentication mode:`**

Only shown for Azure AD / Entra ID. Choose based on whether your tenant allows public client flows:

| Mode | When to use |
|---|---|
| **Public client** | Personal tenant or `Allow public client flows = Yes` in your app — simplest option, no secret needed |
| **Confidential — client secret** | Enterprise tenant with `Allow public client flows = No` — uses a shared app secret |
| **Confidential — certificate** | Enterprise tenant, production recommended — uses a certificate/key pair, no shared secret |

> Check in Azure portal: App registration → Authentication → Advanced settings → "Allow public client flows"

If you choose **certificate mode**, the wizard will ask for two file paths:
- `Path to certificate PEM file:` — enter `~/claude-code-with-bedrock/cert.pem` (works on all platforms)
- `Path to private key PEM file:` — enter `~/claude-code-with-bedrock/key.pem`

Use `~/` relative paths — they resolve correctly on macOS, Linux and Windows. The cert files must exist at those paths on every user machine. See [Certificate Setup](assets/docs/providers/microsoft-entra-id-setup.md#5-confidential-client-setup-enterprise) for how to generate and distribute them.

---

**Q: `Select credential storage method:`**

Choose how the `credential-process` binary stores AWS temporary credentials on the user's machine:

| Option | What it does | When to use |
|---|---|---|
| **Keyring** | OS secure storage (macOS Keychain, Windows Credential Manager, Linux Secret Service) | Production, and recommended for CoWork 3P |
| **Session Files** | Temp files in `~/.aws/credentials` and `~/.claude-code-session/` | Dev/testing — simpler, wiped on logout |

Default is **Session Files**. Both modes work for Claude Code CLI. For **CoWork Desktop 3P**, Keyring is strongly recommended: CoWork resolves credentials through `inferenceBedrockProfile` → boto3's named-profile resolution, and boto3 reads `~/.aws/credentials` before the `credential_process` entry in `~/.aws/config`. In Session Files mode, that means boto3 uses whatever static credentials the last CLI invocation wrote to the file and will **not** auto-refresh them through `credential_process` once they expire — CoWork fails with `403 The security token included in the request is invalid` until the CLI is run again to repopulate the file. Keyring mode keeps `~/.aws/credentials` untouched, so boto3 falls through to `credential_process` and the binary handles refresh transparently. Keyring may show a one-time OS permission prompt on first use.

---

**Q: `Choose federation type:`**

How the OIDC token is exchanged for AWS temporary credentials:

| Option | How it works | Max session | When to use |
|---|---|---|---|
| **Direct STS** | OIDC token → STS `AssumeRoleWithWebIdentity` → temp creds | 12 hours | Recommended for most deployments — simpler, longer sessions |
| **Cognito Identity Pool** | OIDC token → Cognito Identity Pool → temp creds | 8 hours | When you need Cognito features like principal tag mapping |

**Default: Direct STS.** Unless you have a specific reason for Cognito, use Direct STS.

---

##### If you answered No (SSO disabled)

No authentication questions are asked. The wizard skips directly to Step 2.

**What SSO disabled means in practice:**

- **No auth infrastructure is deployed** — no IAM OIDC Provider, no Cognito Identity Pool, no IAM role for developers is created.
- **No `credential_process` binary is distributed** — end users will not get an installer or auto-refreshing AWS credentials from this tool.
- **You are responsible for giving developers Bedrock access** via whatever IAM mechanism already exists in your account (IAM users, existing roles, existing SSO, etc.).

**When to choose No:**

| Scenario | Why disabling SSO makes sense |
|---|---|
| You only want the monitoring/analytics stack | Deploy dashboards without changing how developers authenticate |
| Developers already have Bedrock access via existing roles | Adding another auth layer would be redundant |
| Pilot/testing with a shared IAM user | Fastest way to test the monitoring stack before committing to full OIDC setup |
| You will configure auth manually after deployment | Advanced users who want to customise the CloudFormation templates directly |

> **Note:** Quota monitoring and per-user attribution require SSO enabled. With SSO disabled, the monitoring stack still collects aggregate metrics but cannot attribute usage to individual users.

---

#### Step 2: AWS Infrastructure Configuration

**Q: `Select AWS Region for infrastructure deployment:`**

The region where CloudFormation will create authentication resources (IAM OIDC Provider or Cognito Identity Pool, IAM roles, monitoring stack if enabled). This does **not** have to match the region where Bedrock is invoked — you configure Bedrock regions separately in Step 3.

Choose the region closest to your team or where your compliance requirements dictate resources must reside.

---

**Q: `Stack base name:` (Direct STS) or `Identity Pool Name:` (Cognito)**

A name prefix used for all CloudFormation stack names created by this deployment. Example: `claude-code-auth` produces:
- `claude-code-auth-stack` — main auth stack
- `claude-code-auth-monitoring` — OTEL collector (if enabled)
- `claude-code-auth-dashboard` — CloudWatch dashboard (if enabled)
- `claude-code-auth-analytics` — Athena pipeline (if enabled)

Use lowercase letters, numbers and hyphens only. Must be unique within your AWS account/region.

---

#### Optional Features

---

##### Monitoring and Usage Dashboards

**Q: `Enable monitoring?`**

Deploys an OpenTelemetry collector on ECS Fargate + CloudWatch dashboard showing per-user token usage, costs, model breakdown, and quota status.

- **Yes** → continues to VPC and HTTPS configuration below
- **No** → skips all monitoring questions; auth infrastructure only

> **Important:** If your VPC has no Internet Gateway (fully private environment), answer **No** here. The monitoring ALB is internet-facing by default. See [Known Limitations](#known-limitations) below.

---

**Q: VPC Configuration** (shown if monitoring = Yes)

The wizard asks whether to create a new VPC or use an existing one:

- **Create new VPC** — wizard creates a VPC with public/private subnets automatically. Simplest option.
- **Use existing VPC** — you provide your VPC ID and at least 2 subnet IDs. Use this if you have networking requirements (VPC peering, PrivateLink, specific CIDR ranges).

> Your VPC **must have an Internet Gateway** for monitoring to deploy successfully. This is a current limitation — the OTEL collector ALB is internet-facing.

---

**Q: `Enable HTTPS with custom domain?`**

| Answer | What happens |
|---|---|
| **No** (default) | OTEL collector endpoint uses plain HTTP on the ALB's auto-generated DNS name. Metrics are unencrypted in transit. Simple, no domain needed. |
| **Yes** | Provide a custom domain (e.g. `telemetry.company.com`) and Route53 hosted zone. CloudFormation creates an ACM certificate and DNS record automatically. |

If you answer **Yes**, the wizard asks:
- `Enter custom domain name:` — e.g. `telemetry.company.com`
- `Select Route53 hosted zone:` — the wizard lists zones in your account; select the one that matches your domain

> If you do not have a Route53 hosted zone, answer **No** to HTTPS and handle TLS termination externally.

---

##### Analytics Pipeline

**Q: `Enable analytics?`**

Deploys Kinesis Data Firehose → S3 data lake → Athena with 10 pre-built SQL queries for historical token usage analysis.

- Additional cost: ~$5/month for light usage
- Gives you 90-day hot storage + Glacier archival
- Useful for chargeback, cost attribution by team/department, trend analysis

You can enable this later by re-running `ccwb init` and `ccwb deploy analytics`.

---

##### Quota Monitoring

**Q: `Enable quota monitoring?`**

Enforces per-user monthly and daily token limits. Sends SNS alerts at 80%, 90%, and 100% of limits. Can block credential issuance when limits are exceeded.

If **Yes**, the wizard asks:

**Q: `Monthly token limit per user (in millions):`**
Default: `225` (= 225,000,000 tokens/month). Adjust based on your team's expected usage.

**Q: `Burst buffer percentage (5-25%):`**
Daily limit = (monthly ÷ 30) × (1 + buffer%). The buffer allows for legitimate heavy days above the average without triggering alerts.
- `5%` = strict, blocks heavy days quickly
- `10%` = default, balanced
- `25%` = flexible, only catches extreme spikes

**Q: `Custom daily limit:`**
Press Enter to accept the calculated value, or enter a specific number.

**Q: `Daily limit enforcement:` and `Monthly limit enforcement:`**

| Mode | Behaviour |
|---|---|
| **alert** | Send SNS notification, allow continued use |
| **block** | Deny credential issuance when limit exceeded |

Recommended defaults: Daily = **alert**, Monthly = **block**

**Q: `Quota check interval (minutes):`**
How often quota is re-checked when credentials are cached.
- `0` = check every request (adds ~200ms latency, strictest enforcement)
- `30` = every 30 minutes (default — good balance)
- `60` = hourly (minimal impact, 1-hour enforcement gap)

---

##### Windows Build Support

**Q: `Enable Windows builds?`**

Deploys an AWS CodeBuild project to compile the Windows `.exe` binary using Nuitka. Windows builds take ~20 minutes and run in the cloud — you don't need a Windows machine.

- Answer **Yes** if you have Windows users
- Answer **No** to skip — you can enable it later by re-running `ccwb init`

---

##### Claude Cowork (Desktop) Support

**Q: `Generate CoWork 3P MDM configuration during packaging?`**

When **Yes**, every `ccwb package` run automatically produces MDM configuration files alongside the standard installer. These deploy Claude Desktop (Claude Cowork) pointing at Bedrock through the same credential infrastructure. No extra AWS resources required.

Output files in `dist/cowork-3p/`:
- `cowork-3p.mobileconfig` — deploy via Jamf/Kandji/Mosyle (macOS). Unsigned profiles cannot auto-install: after delivery (or when `install.sh` runs), the user must approve the profile in **System Settings → Privacy & Security → Profiles**.
- `cowork-3p.reg` — deploy via Intune/Group Policy (Windows). Writes to `HKCU\SOFTWARE\Policies\Claude` (per-user, no admin elevation); do not redirect to `HKLM`.
- `cowork-3p-config.json` — raw MDM JSON for the Claude Desktop Setup UI / manual review

Claude Desktop authenticates via the `inferenceBedrockProfile` MDM key, which points at the AWS named profile that `install.sh` / `install.bat` writes to `~/.aws/config`. No per-user wrapper script is required. Users must run the installer **before** opening Claude Desktop — otherwise the named profile won't exist and Bedrock mode won't activate.

See [COWORK_3P.md](assets/docs/COWORK_3P.md) for MDM deployment instructions.

---

##### Package Distribution

**Q: `Distribution method:`**

How to deliver the installer package to end users:

| Option | How it works | Best for |
|---|---|---|
| **Presigned S3 URLs** | `ccwb distribute` uploads to S3 and generates a time-limited link (48h default) you share via Slack/email | Any team size, no extra infrastructure |
| **Authenticated Landing Page** | Self-service web portal — users log in with SSO and download the right binary for their OS | Large orgs needing compliance, audit trail, self-service |
| **Disabled** | You distribute the `dist/` folder manually (zip + email, shared drive, artifact repo) | Simple pilots, internal testing |

If you choose **Landing Page**, the wizard asks for:
- IdP provider for the web portal (can be different from your developer IdP)
- Custom domain for the download portal (e.g. `downloads.company.com`)
- Route53 hosted zone

---

#### Step 3: Bedrock Model Selection

**Q: `Select Claude model:`**

The default model developers will use. This sets `ANTHROPIC_MODEL` in the distributed `settings.json`.

| Model | Cost | Best for |
|---|---|---|
| **Claude Sonnet** | Mid | Most development tasks — best balance of speed and capability |
| **Claude Haiku** | Lowest | High-volume, fast tasks — autocomplete, simple edits |
| **Claude Opus** | Highest | Complex reasoning, architecture, hard problems |

**Q: `Select cross-region inference profile:`**

Routes Bedrock requests across multiple AWS regions within a geography for higher availability and throughput. All regions within a profile have the same pricing.

| Profile | Routes within | Required for Claude 3.7+ |
|---|---|---|
| **US** (`us.`) | US East, US West | Yes — Claude 3.7+ only available via cross-region |
| **EU** (`eu.`) | EU regions | For EU data residency compliance |
| **APAC** (`ap.`) | Asia Pacific regions | For APAC deployments |
| **Global** (`global.`) | All regions worldwide | Maximum throughput |

> **Important:** Claude models 3.7 and newer require cross-region inference. Direct single-region invocation is only available for older models.

**Q: `Select source region:`**

The AWS region where Bedrock API calls originate. Choose the region closest to your developers or your primary AWS region. Requests may be routed to other regions within the profile for capacity, but billing and data residency are anchored to the selected geography.

---

#### What `ccwb init` saves

When the wizard completes, configuration is saved to `~/.ccwb/profiles/<name>.json` on your machine (one file per profile). A `~/.ccwb/config.json` file tracks which profile is currently active.

**Nothing is deployed to AWS at this point.** The wizard only writes local config. Deployment happens in Step 3.

If you need to re-run the wizard to change settings, run `ccwb init` again with the same profile name — it will overwrite the saved profile. If you want to add a second deployment environment, run `ccwb init` again with a new profile name.

---

### Step 3: Deploy Infrastructure

Deploy the AWS CloudFormation stacks:

```bash
poetry run ccwb deploy
```

This deploys in order based on what you configured in Step 2:

**Auth stack** (always deployed):

| Resource | What it does |
|---|---|
| IAM OIDC Provider (Direct STS) or Cognito Identity Pool | Trusts your IdP — validates OIDC tokens from Okta/Azure/Auth0 |
| IAM Role with `bedrock:InvokeModel` | What developers assume after OIDC login — scoped to Bedrock only |
| IAM trust policy | Allows only tokens from your specific IdP client ID to assume the role |

**Monitoring stack** (if monitoring = Yes):

| Resource | What it does |
|---|---|
| ECS Fargate cluster | Runs the ADOT (OpenTelemetry) collector container |
| Application Load Balancer | Receives OTLP metrics from developer machines (port 4318) |
| ACM Certificate + Route53 record | TLS for the OTEL endpoint (if custom domain configured) |
| CloudWatch Log Groups + Metrics | Stores and visualises token usage data |
| CloudWatch Dashboard (`ClaudeCodeMonitoring`) | Per-user token usage, costs, model breakdown |
| DynamoDB table (`UserQuotaMetrics`) | Per-user monthly/daily token totals for quota enforcement |
| Lambda functions | Power custom CloudWatch dashboard widgets |

**Analytics stack** (if analytics = Yes):

| Resource | What it does |
|---|---|
| Kinesis Data Firehose | Streams CloudWatch logs to S3 in Parquet format |
| S3 bucket | 90-day hot storage, auto-transition to Glacier |
| Athena workgroup + 10 named queries | SQL analytics over historical token data |

**Quota stack** (if quota monitoring = Yes):

| Resource | What it does |
|---|---|
| DynamoDB table (`QuotaPolicies`) | Stores per-user/group/default token limits |
| Lambda (quota-monitor) | Runs every 15 min — checks thresholds, sends alerts |
| SNS topic | Delivers quota alerts to subscribed email/webhook |
| API Gateway (quota check) | Real-time quota check at credential issuance time |

**CodeBuild stack** (if Windows builds = Yes):

| Resource | What it does |
|---|---|
| CodeBuild project | Compiles Windows `.exe` using Nuitka (~20 min per build) |
| S3 bucket | Stores compiled Windows binaries |

**Deployment takes 5–15 minutes** depending on which stacks are enabled. Monitor progress:

```bash
poetry run ccwb status
```

#### Known Limitations

> **Monitoring + Private VPC (no Internet Gateway):** The OTEL collector ALB is currently hardcoded as `internet-facing` in the CloudFormation template. If your VPC has no Internet Gateway, the monitoring stack will fail with `VPC has no internet gateway`. **Workaround: disable monitoring during `ccwb init`.** The auth infrastructure deploys without any ALB or IGW requirement.

> **HTTPS disabled + monitoring:** A known bug in older versions of the template causes `Unresolved resource dependencies [HTTPSListener]` when you answer No to HTTPS. If you hit this error, either enable HTTPS (requires a Route53 hosted zone) or disable monitoring entirely.

### Step 4: Create Distribution Package

Build the package for end users:

```bash
# Build all platforms (starts Windows build in background)
poetry run ccwb package --target-platform all

# Check Windows build status (optional)
poetry run ccwb builds

# When ready, create distribution URL (optional)
poetry run ccwb distribute
```

**Choosing macOS targets:**

Before selecting, check your machine's architecture:

```bash
uname -m
python3 -c "import platform; print(platform.machine())"
poetry run python -c "import platform; print(platform.machine())"
```

All three should return the same value. The Poetry command is most important — it confirms what architecture PyInstaller will use when building the binary.

- `arm64` → you are on Apple Silicon — select `macos-arm64`
- `x86_64` → you are on Intel — select `macos-intel`

The `ccwb package` command prompts you to select one or more platforms via a checkbox. **You must build for the architecture your developers are running** — ask your developers to run the same commands on their machines and tell you the output before you build:

```bash
uname -m
python3 -c "import platform; print(platform.machine())"
```

Pick based on what your developers report:

| Your developers report | Select |
|------------------------|--------|
| `arm64` (Apple Silicon) | `macos-arm64` |
| `x86_64` (Intel) | `macos-intel` |
| Both | `macos-arm64` + `macos-intel` |

> **Note:** Building `macos-intel` on an Apple Silicon Mac requires a one-time x86_64 Python setup. If not configured, the Intel build is skipped and **no binary is included in the package**. Complete the [Intel Mac Build Setup](assets/docs/CLI_REFERENCE.md#intel-mac-build-setup-optional) before selecting `macos-intel`.

**Package Workflow:**

1. **Local builds**: macOS/Linux executables are built locally using PyInstaller
2. **Windows builds**: Trigger AWS CodeBuild for Windows executables (20+ minutes) - requires enabling CodeBuild during `init`
3. **Check status**: Monitor build progress with `poetry run ccwb builds`
4. **Create distribution**: Use `distribute` to upload and generate presigned URLs

> **Note**: Windows builds are optional and require CodeBuild to be enabled during the `init` process. If not enabled, the package command will skip Windows builds and continue with other platforms.

The `dist/` folder will contain:

- `credential-process-macos-arm64` - Authentication executable for macOS ARM64
- `credential-process-macos-intel` - Authentication executable for macOS Intel (if built)
- `credential-process-windows.exe` - Authentication executable for Windows
- `credential-process-linux` - Authentication executable for Linux (if built on Linux)
- `config.json` - Embedded configuration
- `install.sh` - Installation script for Unix systems
- `install.bat` - Installation script for Windows
- `README.md` - User instructions
- `.claude/settings.json` - Claude Code telemetry settings (if monitoring enabled)
- `otel-helper-*` - OTEL helper executables for each platform (if monitoring enabled)

The package builder:

- Automatically builds binaries for both macOS and Linux by default
- Uses Docker to cross-compile Linux binaries when running on macOS — **Docker Desktop must be installed and running**; if not present, Linux builds are skipped with a warning and macOS/Windows builds continue unaffected
- Includes the OTEL helper for extracting user attributes from JWT tokens
- Creates a unified installer that auto-detects the user's platform

### Step 5: Test the Setup

Verify everything works correctly:

```bash
poetry run ccwb test
```

This will:

- Simulate the end-user installation process
- Test OIDC authentication
- Verify AWS credential retrieval
- Check Amazon Bedrock access
- (Optional) Test actual API calls with `--api` flag

### Step 6: Distribute Packages to Users

You have three options for sharing packages with users. The distribution method is configured during `ccwb init` (Step 2).

#### Option 1: Manual Sharing

No additional infrastructure required. Share the built packages directly:

```bash
# Navigate to dist directory
cd dist

# Create a zip file of all packages
zip -r claude-code-packages.zip .

# Share via email or internal file sharing
# Users extract and run install.sh (Unix) or install.bat (Windows)
```

**Best for:** Any size team, no automation required

#### Option 2: Presigned S3 URLs

Automated distribution via time-limited S3 URLs:

```bash
poetry run ccwb distribute
```

Generates presigned URLs (default 48-hour expiry) that you share with users via email or messaging.

**Best for:** Automated distribution without authentication requirements

**Setup:** Select "presigned-s3" distribution type during `ccwb init` (Step 2)

#### Option 3: Authenticated Landing Page

Self-service portal with IdP authentication:

```bash
# Deploy landing page infrastructure (if not done during Step 3)
poetry run ccwb deploy distribution

# Upload packages to landing page
poetry run ccwb distribute
```

Users visit your landing page URL, authenticate with SSO, and download packages for their platform.

**Best for:** Self-service portal with compliance and audit requirements

**Setup:** Select "landing-page" distribution type during `ccwb init` (Step 2), then deploy distribution infrastructure

See [Distribution Comparison](assets/docs/distribution/comparison.md) for detailed feature comparison and setup guides.

---

## Platform Builds

### Build Requirements

- **Windows**: AWS CodeBuild with Nuitka (automated)
- **macOS**: PyInstaller with architecture-specific builds
  - ARM64: Native build on Apple Silicon Macs
  - Intel: Optional - requires x86_64 Python environment on ARM Macs
  - Universal: Requires both architectures' Python libraries
- **Linux**: Docker with PyInstaller (cross-compiled from macOS host)
  - Requires [Docker Desktop](https://docs.docker.com/get-docker/) installed and running
  - If Docker is not installed or its daemon is not running, Linux builds are skipped with a warning
  - macOS and Windows builds have **no dependency on Docker**

### Optional: Intel Mac Builds

Intel Mac builds require an x86_64 Python environment on Apple Silicon Macs.

See [CLI Reference - Intel Mac Build Setup](assets/docs/CLI_REFERENCE.md#intel-mac-build-setup-optional) for setup instructions.

If not configured, the package command will skip Intel builds and continue with other platforms.

---

## Cleanup

You are responsible for the costs of AWS services while running this guidance. If you decide that you no longer need the guidance, please ensure that infrastructure resources are removed.

```bash
poetry run ccwb destroy
```

---

## Troubleshooting

### `ccwb init` fails "AWS credentials configured" even though `aws sts get-caller-identity` works

This is almost always caused by **expired AWS environment variables** overriding your credential file. boto3 (used internally by `ccwb`) resolves credentials in a strict priority order and stops at the first source that provides values — even if those values are expired:

```
1. AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY env vars   ← highest priority
2. ~/.aws/credentials file
3. ~/.aws/config file (SSO, credential_process, assumed roles)
4. IAM instance profile (EC2 only)
5. ECS container role                                   ← lowest priority
```

If `AWS_ACCESS_KEY_ID` is set in your environment but expired, boto3 will **not** fall back to `~/.aws/credentials`. It will simply fail. This is the most common cause of this error.

**Fix:**

```bash
# 1. Check what is set
env | grep AWS_

# 2. Unset any stale values
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

# 3. Verify boto3 now resolves credentials correctly
python3 -c "import boto3; print(boto3.client('sts').get_caller_identity())"

# 4. Re-run init
poetry run ccwb init
```

If you are using `aws sso login`, make sure the SSO session is active before running `ccwb init`:

```bash
aws sso login --profile <your-profile>
export AWS_PROFILE=<your-profile>
poetry run ccwb init
```

### Authentication Issues (end-user credential refresh)

Force re-authentication after deployment:

```bash
~/claude-code-with-bedrock/credential-process --clear-cache
```

If CoWork Desktop 3P fails with `403 The security token included in the request is invalid` and the user was previously on a session-files build, `~/.aws/credentials` may contain a stale `[<profile-name>]` stanza with literal `EXPIRED` values that shadows the current `credential_process` entry in `~/.aws/config`. Re-run `install.sh` / `install.bat` — it purges any such stanza before writing the new profile. Alternatively, remove the block by hand.

### Port Conflicts

The credential provider uses port 8400 by default for OAuth callbacks.
If this port is in use by another application, authentication will automatically use an available port.

To manually specify a different port, set the `REDIRECT_PORT` environment variable:

```bash
export REDIRECT_PORT=8401
```

### `Exec format error` on the credential-process binary (end user)

If an end user sees this when running `aws sts get-caller-identity` or launching Claude:

```
[Errno 8] Exec format error: '/Users/<username>/claude-code-with-bedrock/credential-process'
```

or directly:

```
zsh: exec format error: ./credential-process
```

**This is a CPU architecture mismatch** — the binary was built for a different architecture than the user's machine. `chmod +x` will not fix it.

**Diagnose (run on the user's machine):**

```bash
uname -m                                                  # their CPU arch
file ~/claude-code-with-bedrock/credential-process        # binary's CPU arch
```

| `uname -m` result | Binary arch | Cause |
|---|---|---|
| `x86_64` (Intel Mac) | `arm64` | Intel binary was not built — only ARM64 was in the package |
| `arm64` (Apple Silicon) | `x86_64` | Wrong binary manually copied |

**Fix (admin) — rebuild with both macOS architectures:**

```bash
# One-time setup: x86_64 Python environment on Apple Silicon Mac
arch -x86_64 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
arch -x86_64 /usr/local/bin/brew install python@3.12
arch -x86_64 /usr/local/bin/python3.12 -m venv ~/venv-x86
arch -x86_64 ~/venv-x86/bin/pip install pyinstaller boto3 keyring

# Rebuild — now produces both macos-arm64 and macos-intel
poetry run ccwb package --target-platform all
```

Redistribute the new package. The installer auto-detects architecture and installs the correct binary.

> **Why this happens:** Building on Apple Silicon only produces `credential-process-macos-arm64` by default. The Intel (`macos-intel`) build is optional and requires the x86_64 Python environment above. ARM64 binaries cannot run on Intel Macs — unlike the reverse (Intel binaries run on Apple Silicon via Rosetta).

### Windows `install.bat` — `-replace was unexpected at this time.`

If running `install.bat` on Windows produces this error:

```
-replace was unexpected at this time.
```

**Root cause:** This is a cmd.exe parser bug in the generated installer — `^` line-continuation characters inside a double-quoted PowerShell command get consumed by cmd.exe, causing `-replace` to be treated as a standalone batch command rather than part of the PowerShell string. A code fix is included in the next release.

**Workaround:** The binary and `config.json` are already copied before this error occurs — only the `~/.claude/settings.json` placeholder replacement fails. Complete the installation manually:

**Step 1** — Open **PowerShell** (not cmd.exe) from the extracted package folder and run:

```powershell
$otelPath = "$env:USERPROFILE\claude-code-with-bedrock\otel-helper.exe" -replace '\\', '/'
$credPath = "$env:USERPROFILE\claude-code-with-bedrock\credential-process.exe" -replace '\\', '/'
(Get-Content 'claude-settings\settings.json') `
    -replace '__OTEL_HELPER_PATH__', $otelPath `
    -replace '__CREDENTIAL_PROCESS_PATH__', $credPath |
    Set-Content "$env:USERPROFILE\.claude\settings.json"
```

**Step 2** — Configure the AWS profile (replace `<profile-name>` with the name shown in `config.json`):

```powershell
aws configure set credential_process `
    "$env:USERPROFILE\claude-code-with-bedrock\credential-process.exe --profile <profile-name>" `
    --profile <profile-name>
```

> **Why PowerShell works:** PowerShell uses backtick (`` ` ``) for line continuation — there is no cmd.exe parser involved to mangle the `-replace` operators.

### Build Failures

Check Windows build status:

```bash
poetry run ccwb builds
```

### Stack Deployment Issues

View stack status:

```bash
poetry run ccwb status
```

For detailed troubleshooting, see [Deployment Guide](assets/docs/DEPLOYMENT.md).

---

## Next Steps

- [Architecture Deep Dive](assets/docs/ARCHITECTURE.md) - Technical architecture details
- [Enable Monitoring](assets/docs/MONITORING.md) - Setup OpenTelemetry monitoring
- [Setup Analytics](assets/docs/ANALYTICS.md) - Configure S3 data lake and Athena queries
- [CLI Reference](assets/docs/CLI_REFERENCE.md) - Complete command reference
