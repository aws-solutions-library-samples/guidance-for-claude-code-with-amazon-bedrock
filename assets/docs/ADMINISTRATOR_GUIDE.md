# Administrator Guide

This guide covers ongoing administration after the initial `ccwb init` and `ccwb deploy` are complete. It focuses on user onboarding, quota management, monitoring, package distribution, and operational tasks.

---

## How User Access Works

### Self-Service via Identity Provider (IdP)

User onboarding is **primarily managed through your Identity Provider**, not through the `ccwb` CLI. The system federates your existing IdP with AWS IAM, so:

- **Adding a user** = adding them in your IdP (Okta, Azure AD, Auth0, Cognito User Pool) and assigning them to the appropriate application
- **Removing a user** = removing them from the IdP application or disabling their IdP account
- **Group membership** = managed in your IdP's group/role system

There is no `ccwb add-user` command. Once a user has the installation package and is authorized in your IdP, they can authenticate and get AWS credentials automatically. The IAM trust policy accepts any valid token from the configured OIDC provider and client ID — individual users are not whitelisted at the AWS level.

### What the Administrator Controls

| Concern | Where It's Managed |
|---------|-------------------|
| Who can authenticate | Identity Provider (Okta/Azure AD/Auth0/Cognito) |
| Who can access Bedrock | Same — if they can authenticate, they can access Bedrock |
| How much a user can consume | `ccwb quota` commands (DynamoDB-backed policies) |
| Which Bedrock regions are allowed | IAM policy in CloudFormation stack (set during `ccwb init`) |
| Which Claude model is used | Embedded in the package (`config.json` / `settings.json`) |
| Usage visibility | CloudWatch dashboards (if monitoring was enabled) |

### Onboarding a New User — Step by Step

1. **Add the user to your IdP application.** In Okta, this means assigning the user to the OIDC app. In Azure AD, it means adding them to the Enterprise Application. In Cognito, it means creating a user in the User Pool or letting them self-register.

2. **Assign them to IdP groups** (if using group-based quota policies). The group claim in their JWT token is what the quota system evaluates.

3. **Optionally set a user-specific quota:**
   ```
   poetry run ccwb quota set-user alice@company.com --monthly-limit 300M --enforcement block
   ```
   If you don't, they fall back to the group policy or the default policy.

4. **Give them the installation package.** This is the same package for all users — it contains no user-specific information. Distribution options:
   - Share the `dist/` folder directly (zip + email/Slack)
   - Generate a presigned S3 URL: `poetry run ccwb distribute`
   - Direct them to the self-service landing page (if deployed)

5. **That's it.** The user runs the installer, and on first use, their browser opens to authenticate with the IdP. No further admin action needed.

### Offboarding a User

1. **Remove or disable them in the IdP.** Their existing AWS credentials expire within 8-12 hours (depending on federation type). New credentials cannot be obtained.

2. **Optionally delete their quota policy:**
   ```
   poetry run ccwb quota delete user alice@company.com
   ```

3. **No need to revoke packages.** The package itself has no embedded user credentials — it only contains the OIDC client ID (a public value) and federation configuration. Without a valid IdP account, the package is useless.

---

## Package Building and Distribution

After initial deployment, the primary ongoing task is building and distributing installation packages whenever configuration changes (new model, new region, monitoring endpoint changes, etc.).

### Building Packages

```
poetry run ccwb package
```

The wizard prompts for:

| Prompt | Options | Notes |
|--------|---------|-------|
| Target platforms | `macos-arm64`, `macos-intel`, `linux-x64`, `linux-arm64`, `windows` (checkbox) | Select all platforms your users need. Windows requires CodeBuild to be enabled. |
| Co-Authored-By in git commits | Yes / No | Whether Claude Code adds "Co-Authored-By: Claude" to users' git commits. |

The output goes to `dist/{profile-name}/{timestamp}/` and contains:

```
dist/my-profile/2025-02-12-143022/
├── credential-process-macos-arm64      # macOS Apple Silicon binary
├── credential-process-macos-intel      # macOS Intel binary
├── credential-process-linux-x64        # Linux x86_64 binary
├── credential-process-linux-arm64      # Linux ARM64 binary
├── credential-process-windows.exe      # Windows binary (if CodeBuild enabled)
├── config.json                         # OIDC + federation configuration
├── install.sh                          # macOS/Linux installer
├── install.bat                         # Windows installer
├── otel-helper-macos-arm64             # Telemetry helper (if monitoring enabled)
├── otel-helper-linux-x64              # ...per platform
└── claude-settings/
    └── settings.json                   # Claude Code environment settings
```

**When to rebuild packages:**
- You changed the Claude model in `ccwb init`
- You enabled/disabled monitoring
- You changed the cross-region inference profile
- The monitoring endpoint changed (redeployed the OTEL stack)
- You want to change the "Co-Authored-By" setting

**When you do NOT need to rebuild:**
- A new user joins (same package works for everyone)
- You changed quota policies (quotas are server-side, not in the package)
- A user's IdP group changed (evaluated at auth time from their JWT)

### Distributing Packages

#### Option 1: Manual Sharing

Zip the `dist/{profile}/{timestamp}/` directory and share via email, Slack, or internal file server. Simplest approach, no infrastructure needed.

#### Option 2: Presigned S3 URLs

```
poetry run ccwb distribute
```

The command:
1. Prompts you to select which build to distribute (by profile/timestamp)
2. Uploads the package to S3
3. Generates a time-limited download URL (default: 48 hours, configurable 1-168 hours)
4. Optionally generates a QR code (`--show-qr`)
5. Optionally restricts by IP range (`--allowed-ips 10.0.0.0/8,192.168.0.0/16`)

Useful flags:
```
poetry run ccwb distribute --latest              # Auto-select most recent build
poetry run ccwb distribute --expires-hours 72     # 3-day URL
poetry run ccwb distribute --get-latest           # Retrieve the last generated URL
```

#### Option 3: Self-Service Landing Page

If you deployed the landing page during `ccwb init`, users visit a web URL (e.g., `https://downloads.company.com`), authenticate with the IdP, and the page auto-detects their platform and offers the correct download. No admin action needed per user — the landing page always serves the latest uploaded build.

---

## Quota Management

For a detailed explanation of how the quota system works — policy hierarchy, enforcement timing, enforcement gaps, fail modes, and architecture — see the [Quota Management Guide](QUOTA_MANAGEMENT.md). This section covers the CLI commands for day-to-day quota administration.

### Setting Quotas

**Per-user:**
```
poetry run ccwb quota set-user alice@company.com \
  --monthly-limit 300M \
  --daily-limit 15M \
  --enforcement block
```

**Per-group:**
```
poetry run ccwb quota set-group engineering \
  --monthly-limit 500M \
  --enforcement alert
```

**Default (all users):**
```
poetry run ccwb quota set-default \
  --monthly-limit 225M \
  --enforcement block
```

Token limit shortcuts: `225M` = 225,000,000 tokens, `1B` = 1,000,000,000, `500K` = 500,000.

### Viewing and Monitoring Quotas

**List all policies:**
```
poetry run ccwb quota list
poetry run ccwb quota list --type user    # Only user policies
poetry run ccwb quota list --type group   # Only group policies
```

**See what policy applies to a specific user:**
```
poetry run ccwb quota show alice@company.com
poetry run ccwb quota show alice@company.com --groups engineering,senior-devs
```

**Check current usage:**
```
poetry run ccwb quota usage alice@company.com
```
Outputs current consumption vs. limits with percentage and color-coded warnings.

### Emergency Unblock

If a user is blocked and needs temporary access:
```
poetry run ccwb quota unblock alice@company.com --duration 24h --reason "Deadline for project X"
```

Duration options: `24h` (default), up to `7d` (hard maximum), or `until-reset` (until the monthly counter resets). An audit trail records who unblocked, when, and why.

### Bulk Management

**Export all policies to CSV:**
```
poetry run ccwb quota export policies.csv
```

**Edit the CSV, then import:**
```
poetry run ccwb quota import policies.csv --update --auto-daily --burst 10
```

The `--auto-daily` flag auto-calculates daily limits from monthly (monthly/30 * (1 + burst%)). The `--dry-run` flag previews changes without applying them.

**CSV format:**
```csv
type,identifier,monthly_token_limit,daily_token_limit,enforcement_mode,enabled
user,alice@company.com,300000000,15000000,block,true
group,engineering,500000000,,alert,true
default,default,225000000,8250000,block,true
```

### Deleting Quotas

```
poetry run ccwb quota delete user alice@company.com
poetry run ccwb quota delete group engineering
poetry run ccwb quota delete default default
```

---

## Monitoring and Dashboards

If monitoring was enabled during init, usage data flows through:

```
Claude Code → OTEL Collector (ECS Fargate) → CloudWatch Logs → Dashboards
                                           ↘ Kinesis Firehose → S3 → Athena (if analytics enabled)
```

### CloudWatch Dashboards

The dashboard stack deploys 19 custom Lambda-backed widgets showing:

- **Active users** — unique users over time
- **Token consumption** — by user, model, and type (input/output/cache)
- **Top consumers** — top 10 users by token usage
- **Prompt cache efficiency** — hit rates and token savings
- **Code activity** — lines of code generated, files edited, languages used
- **Usage heatmaps** — hourly/daily activity patterns
- **Quota status** — real-time quota utilization (if quota monitoring enabled)

Access these dashboards in the CloudWatch console in your deployment region.

### Athena Analytics (if enabled)

For ad-hoc SQL queries over historical data:
```sql
-- Example: Top 10 users by monthly token consumption
SELECT user_email, SUM(total_tokens) as total
FROM claude_code_metrics
WHERE month = '2025-02'
GROUP BY user_email
ORDER BY total DESC
LIMIT 10;
```

Pre-built queries are deployed via the `logs-insights-queries.yaml` stack.

---

## Operational Commands

### Check Deployment Status

```
poetry run ccwb status
poetry run ccwb status --detailed
poetry run ccwb status --json
```

Shows: configuration summary, CloudFormation stack statuses, endpoints, and health.

### Validate Configuration

```
poetry run ccwb config validate
poetry run ccwb config validate all    # Validate all profiles
```

### Test End-to-End Authentication

```
poetry run ccwb test
```

Validates: package contents, credential-process execution, OIDC authentication, IAM role assumption, Bedrock API access in configured regions.

```
poetry run ccwb test --quota-only      # Test just the quota system
poetry run ccwb test --full            # Test all regions (not just sample)
```

### Manage Multiple Deployment Profiles

If you manage multiple environments (dev/staging/prod) or multiple AWS accounts:

```
poetry run ccwb context list           # List all profiles
poetry run ccwb context use prod       # Switch active profile
poetry run ccwb context show prod      # View profile details
poetry run ccwb context current        # Show which profile is active
```

All `ccwb` commands operate on the active profile unless `--profile <name>` is specified.

### Check Windows Build Status

```
poetry run ccwb builds                         # List recent builds
poetry run ccwb builds --status latest         # Check latest build
poetry run ccwb builds --status <build-id>     # Check specific build
```

### Teardown

```
poetry run ccwb destroy                # Interactive — select which stacks to remove
poetry run ccwb destroy auth           # Remove just the auth stack
poetry run ccwb destroy --force        # Skip confirmation prompts
```

Stacks are deleted in dependency order: analytics → dashboard → monitoring → networking → s3bucket → auth. The command reports any resources that need manual cleanup (non-empty S3 buckets, log groups, etc.).

### Cleanup End-User Installations

If users need to reinstall or you need to clear their cached credentials:

```
poetry run ccwb cleanup                    # Remove installed components
poetry run ccwb cleanup --credentials-only # Just clear cached credentials
```

---

## Updating the Deployment

### Changing Configuration

1. Run `poetry run ccwb init` and choose "Update existing profile"
2. Walk through the wizard — existing values are pre-filled as defaults
3. Run `poetry run ccwb deploy` to apply CloudFormation changes
4. If the change affects the end-user package (model, monitoring endpoint, etc.), rebuild and redistribute: `poetry run ccwb package` then `poetry run ccwb distribute`

### What Requires Redeployment vs. Rebuild

| Change | Action Needed |
|--------|--------------|
| Add/remove users | IdP only — no ccwb action |
| Change quota policies | `ccwb quota` commands — no deploy or rebuild |
| Change Claude model | `ccwb init` (update) → `ccwb deploy` → `ccwb package` → distribute |
| Enable/disable monitoring | `ccwb init` (update) → `ccwb deploy` → `ccwb package` → distribute |
| Change allowed Bedrock regions | `ccwb init` (update) → `ccwb deploy` → `ccwb package` → distribute |
| Change federation type | `ccwb init` (update) → `ccwb deploy` → `ccwb package` → distribute |
| Change OIDC client ID | `ccwb init` (update) → `ccwb deploy` → `ccwb package` → distribute |
| Change VPC configuration | `ccwb init` (update) → `ccwb deploy` |
| Rotate IdP client secret (landing page) | Re-run `ccwb init` landing page section or update Secrets Manager directly |

---

## Security Considerations

- **Credentials are temporary.** Direct STS sessions last up to 12 hours; Cognito sessions up to 8 hours. No long-lived secrets are stored.
- **PKCE protects the auth flow.** The OAuth2 authorization code flow uses Proof Key for Code Exchange, preventing authorization code interception.
- **IAM policies are scoped.** The federated role only permits Bedrock invocation in the configured regions, plus optional CloudWatch metrics publishing. No S3, EC2, Lambda, or other service access.
- **Session tags enable auditing.** Every AWS API call made via the federated credentials includes the user's email, subject ID, and name as session tags, which appear in CloudTrail.
- **Packages contain no secrets.** The `config.json` in the distribution package contains only the OIDC client ID (a public identifier), federation configuration, and model settings. No client secrets, no AWS credentials.
- **Quota enforcement is server-side.** Even if a user tampers with their local binary to skip the quota check, the quota API is called during credential refresh — and the Lambda function enforces the policy.

---

## Command Reference Summary

| Command | Purpose |
|---------|---------|
| `ccwb init` | Configure or update a deployment profile |
| `ccwb deploy` | Deploy/update CloudFormation stacks |
| `ccwb package` | Build platform-specific installation packages |
| `ccwb distribute` | Upload packages and generate download URLs |
| `ccwb test` | Validate end-to-end authentication and Bedrock access |
| `ccwb status` | Check deployment health and stack statuses |
| `ccwb quota set-user/set-group/set-default` | Set token quotas |
| `ccwb quota list/show/usage` | View quotas and consumption |
| `ccwb quota unblock` | Emergency temporary override |
| `ccwb quota export/import` | Bulk policy management |
| `ccwb quota delete` | Remove a policy |
| `ccwb context list/use/show/current` | Manage deployment profiles |
| `ccwb config validate/export/import` | Configuration management |
| `ccwb builds` | Check Windows build status |
| `ccwb cleanup` | Remove installed components |
| `ccwb destroy` | Tear down CloudFormation stacks |
