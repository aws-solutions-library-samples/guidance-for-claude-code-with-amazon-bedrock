![E2E Tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock/feat/e2e-matrix-harness/tests/e2e/badge.json)

# E2E Test Harness

Profile-driven end-to-end testing across authentication flows, operating systems, monitoring modes, config delivery mechanisms, and quota enforcement strategies.

## Platform Focus

Windows and macOS receive extra testing attention due to historical platform-specific issues:

| Issue | Platform | Problem |
|-------|----------|---------|
| #427 | Windows | `install.bat` syntax errors (`& was unexpected`) |
| #428 | Windows | CRLF line endings in generated `.sh` scripts |
| #349 | macOS | Keychain integration failures |
| #567 | Windows | `.cmd` fallback not invoking `.ps1` correctly |
| #649 | Windows | DPAPI keyring retrieval taking 10-17s |
| #664 | macOS | ARM64 binary detection / Rosetta fallback |

Profiles 13-16 specifically target these platforms with stress scenarios (keyring chunking under load, sidecar monitoring, quota enforcement). The PR canary runs both Linux (profile 01) and Windows (profile 04) to catch regressions before merge.

## How It Works

Each test scenario is defined by a **profile JSON** file in `tests/e2e/profiles/`. A profile declares:

- **Auth type**: OIDC (Cognito/Direct STS), IDC (device auth), or Passthrough (ambient creds)
- **Platform**: linux-x64, windows-x64, macos-arm64
- **Monitoring mode**: central (port 4318), sidecar (port 4319), or none
- **Config delivery**: static (env vars) or bootstrap (API endpoint)
- **Quota**: enabled/disabled, enforcement mode (block/alert), fine-grained policies
- **Tests**: which test modules apply to this profile

The test harness automatically skips test modules not declared in the active profile.

## Running Locally

### Prerequisites

1. AWS credentials with access to deploy E2E stacks
2. Python 3.11+ with test dependencies
3. Built binaries for your platform

### Setup

```bash
# Install dependencies
pip install pytest pytest-timeout boto3 requests tenacity PyJWT

# Build binaries (from source/go/)
cd source/go
go build -o dist/credential-process-linux-amd64 ./cmd/credential-process/
go build -o dist/otel-helper-linux-amd64 ./cmd/otel-helper/
cd ../..

# Deploy E2E infrastructure (optional — needed for integration tests)
cd deployment
cdk deploy -c e2eMode=true ccwb-e2e-local-auth ccwb-e2e-local-monitoring ccwb-e2e-local-quota ccwb-e2e-local-config
cd ..
```

### Run Tests

```bash
# Run a specific profile
pytest tests/e2e/ --profile 01-oidc-cognito-linux-central -v

# Run with environment variable
E2E_PROFILE=09-passthrough-linux-none pytest tests/e2e/ -v

# Skip slow tests (CloudWatch assertions)
pytest tests/e2e/ --profile 01-oidc-cognito-linux-central -v -m "not slow"

# Run only auth tests
pytest tests/e2e/test_auth_flow.py --profile 01-oidc-cognito-linux-central -v
```

### Without AWS Infrastructure

Tests skip gracefully when AWS credentials or stack outputs are unavailable:

```bash
# This will skip integration tests but validate test structure
pytest tests/e2e/ --profile 09-passthrough-linux-none --co
```

## Adding a New Scenario

1. Create a profile JSON in `tests/e2e/profiles/`:

```json
{
  "name": "13-my-new-scenario",
  "description": "Description of what this tests",
  "auth": {"type": "oidc", "federation": "direct", "provider": "okta"},
  "platform": "linux-x64",
  "monitoring": {"mode": "central"},
  "config_delivery": "static",
  "quota": {"enabled": false},
  "tests": ["auth_flow", "credential_output", "monitoring_pipeline"]
}
```

2. Add to the matrix in `.github/workflows/e2e-matrix.yml`:

```yaml
- profile: '13-my-new-scenario'
  os: ubuntu-latest
  platform: linux-x64
```

3. Commit and push — CI will pick it up automatically.

## Branch Support

This harness runs on the **`beta` branch only** — beta is the validation gate before promoting to main.

| Trigger | Branch | Behavior |
|---------|--------|----------|
| Nightly (3 AM UTC, weekdays) | `beta` | Full 16-profile matrix |
| PRs targeting `beta` | `beta` | Smoke only (profile 09 + Windows canary) — fast feedback, no infra cost |
| Manual dispatch | Any branch | Full matrix or single profile (`-f profile=...`) |
| `main` | — | No E2E runs. Releases are validated on beta first. |

The workflow skips if triggered on `main` by the cron scheduler.

## CI Setup (One-Time, ~10 minutes)

### Prerequisites

- AWS account with CloudFormation access
- Repository admin access (for secrets/environments)
- `aws` CLI configured locally (for the OIDC trust setup)

### Step 1: Create GitHub OIDC Identity Provider

This allows GitHub Actions to authenticate to AWS without long-lived secrets.

```bash
# Check if OIDC provider already exists
aws iam list-open-id-connect-providers | grep token.actions.githubusercontent.com

# If not, create it:
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
  --client-id-list sts.amazonaws.com
```

> **Note:** Most AWS accounts already have this provider (used by many GitHub Actions workflows). If it exists, skip this step.

### Step 2: Create the E2E IAM Role

```bash
# Get your AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create trust policy (replace OWNER/REPO with your fork)
cat > /tmp/e2e-trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:OWNER/REPO:*"
        }
      }
    }
  ]
}
EOF

# Replace placeholders
sed -i "s/ACCOUNT_ID/$ACCOUNT_ID/g" /tmp/e2e-trust-policy.json
sed -i "s|OWNER/REPO|wirjo/guidance-for-claude-code-with-amazon-bedrock|g" /tmp/e2e-trust-policy.json

# Create the role
aws iam create-role \
  --role-name ccwb-e2e-github-actions \
  --assume-role-policy-document file:///tmp/e2e-trust-policy.json

# Attach permissions (CloudFormation + resources the stacks create)
aws iam attach-role-policy \
  --role-name ccwb-e2e-github-actions \
  --policy-arn arn:aws:iam::aws:policy/PowerUserAccess

# Get the role ARN (you'll need this in Step 3)
aws iam get-role --role-name ccwb-e2e-github-actions --query Role.Arn --output text
```

> **Security note:** `PowerUserAccess` is broad. For production, scope down to CloudFormation, DynamoDB, CloudWatch, Lambda, IAM (create/delete roles with path prefix), and S3. The E2E stacks are ephemeral (~20 min lifetime) so blast radius is limited.

### Step 3: Configure GitHub Repository

```bash
# Set the role ARN as a repository variable
gh variable set E2E_AWS_ROLE_ARN --body "arn:aws:iam::123456789012:role/ccwb-e2e-github-actions"

# Create the protected environment (provides audit trail + optional reviewers)
gh api repos/{owner}/{repo}/environments/e2e-testing -X PUT
```

Or via GitHub UI:
1. **Settings → Variables → Actions** → New variable: `E2E_AWS_ROLE_ARN` = your role ARN
2. **Settings → Environments** → New: `e2e-testing` (optionally add reviewers for manual dispatch)

### Step 4: Verify

```bash
# Trigger a manual run with a single profile (cheapest test)
gh workflow run e2e-matrix.yml -f profile=09-passthrough-linux-none

# Watch the run
gh run watch
```

If the smoke job passes, you're good. The passthrough profile doesn't need any infra, so it validates the workflow mechanics without AWS cost.

### Troubleshooting Setup

| Problem | Fix |
|---------|-----|
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Check trust policy — repo name must match exactly (case-sensitive) |
| `No OpenIDConnect provider found` | Run Step 1 to create the OIDC provider |
| Workflow not triggering on PRs | Check that PR modifies files under `deployment/` or `source/go/` |
| `E2E_AWS_ROLE_ARN` not found | Set as **repository variable** (not secret) — secrets aren't visible in fork PRs |
| Stack creation failed | Check CloudFormation events. Most common: IAM permission boundary blocking role creation |

## Cost Estimate

Running the full nightly matrix costs approximately **$0.50/month**:

| Resource | Cost |
|----------|------|
| CloudFormation stacks (deployed ~20 min/night) | ~$0.10/month |
| DynamoDB on-demand (test writes) | ~$0.01/month |
| CloudWatch metrics/logs | ~$0.15/month |
| GitHub Actions minutes (12 jobs × 10 min) | ~$0.24/month |
| **Total** | **~$0.50/month** |

## Profile Coverage Matrix

| # | Profile | Auth | Platform | Monitoring | Delivery | Quota |
|---|---------|------|----------|------------|----------|-------|
| 01 | oidc-cognito-linux-central | OIDC/Cognito | Linux | Central | Static | — |
| 02 | oidc-direct-linux-central-block | OIDC/Direct | Linux | Central | Static | Block |
| 03 | oidc-direct-linux-bootstrap-alert | OIDC/Direct | Linux | Central | Bootstrap | Alert |
| 04 | oidc-cognito-windows-central | OIDC/Cognito | Windows | Central | Static | — |
| 05 | oidc-direct-windows-none | OIDC/Direct | Windows | None | Static | — |
| 06 | oidc-direct-macos-sidecar-finegrained | OIDC/Direct | macOS | Sidecar | Static | Block+FG |
| 07 | idc-linux-central-block | IDC | Linux | Central | Static | Block/SigV4 |
| 08 | idc-windows-sidecar | IDC | Windows | Sidecar | Static | — |
| 09 | passthrough-linux-none | Passthrough | Linux | None | Static | — |
| 10 | oidc-direct-linux-bootstrap-finegrained | OIDC/Direct | Linux | Central | Bootstrap | Block+FG |
| 11 | oidc-direct-linux-sidecar-block | OIDC/Direct | Linux | Sidecar | Static | Block |
| 12 | oidc-cognito-macos-central-alert | OIDC/Cognito | macOS | Central | Static | Alert |
| 13 | oidc-direct-windows-sidecar-alert | OIDC/Direct | Windows | Sidecar | Static | Alert |
| 14 | oidc-cognito-windows-central-block | OIDC/Cognito | Windows | Central | Static | Block |
| 15 | oidc-direct-macos-central-block | OIDC/Direct | macOS | Central | Static | Block |
| 16 | idc-macos-sidecar | IDC | macOS | Sidecar | Static | — |

### Dimensions Covered

- **Auth types**: OIDC (Cognito federation, Direct STS), IDC (device auth), Passthrough
- **IdP providers**: Cognito, Okta, Azure AD
- **Platforms**: Linux x64, Windows x64, macOS ARM64
- **Monitoring**: Central (port 4318), Sidecar (port 4319), None
- **Config delivery**: Static (env vars), Bootstrap (API)
- **Quota enforcement**: Block, Alert, Fine-grained (DynamoDB policies), SigV4 auth
- **Quota auth**: API key, SigV4

## Debugging Failures

### Keep Infrastructure

Use `--keep-infra` in manual workflow dispatch to prevent teardown:

```
gh workflow run e2e-matrix.yml -f keep_infra=true -f profile=01-oidc-cognito-linux-central
```

### Local Debugging

```bash
# Run with verbose output
pytest tests/e2e/ --profile 01-oidc-cognito-linux-central -v -s --tb=long

# Run single test
pytest tests/e2e/test_auth_flow.py::TestAuthFlow::test_initial_auth_produces_valid_creds \
  --profile 01-oidc-cognito-linux-central -v -s

# Check what would run (collect only)
pytest tests/e2e/ --profile 01-oidc-cognito-linux-central --co
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| All tests skip | No `--profile` or `E2E_PROFILE` set | Set profile |
| Binary not found | Wrong platform or build missing | Check `source/go/dist/` |
| Stack outputs missing | Infrastructure not deployed | Deploy stacks or set `E2E_STACK_OUTPUTS` |
| CloudWatch test timeout | Metric propagation delay | Increase retry timeout or mark as slow |
| Port not listening | Proxy failed to start | Check binary stderr, system ports |

## Test Markers

- `@pytest.mark.e2e` — All E2E tests (use `-m e2e` to run only E2E)
- `@pytest.mark.slow` — Tests with long waits (CloudWatch propagation)

## File Structure

```
tests/e2e/
├── conftest.py              # Shared fixtures, CLI args, skip logic
├── helpers.py               # Shared utility functions (extracted from conftest)
├── profiles/                # Profile JSON definitions
│   ├── 01-oidc-cognito-linux-central.json
│   ├── 02-oidc-direct-linux-central-block.json
│   ├── ...
│   ├── 13-oidc-direct-windows-sidecar-alert.json
│   ├── 14-oidc-cognito-windows-central-block.json
│   ├── 15-oidc-direct-macos-central-block.json
│   └── 16-idc-macos-sidecar.json
├── test_auth_flow.py        # Authentication tests
├── test_credential_output.py # Output format tests
├── test_monitoring_pipeline.py # OTLP proxy tests
├── test_quota_enforcement.py # Quota tests
├── test_config_delivery.py  # Bootstrap config tests
├── test_binary_platform.py  # Platform-specific tests (Windows + macOS)
├── artifacts/               # (gitignored) Stack outputs at runtime
└── README.md                # This file
```
