# E2E Test Harness

Profile-driven end-to-end testing across authentication flows, operating systems, monitoring modes, config delivery mechanisms, and quota enforcement strategies.

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

## CI Setup

### GitHub OIDC Trust

The workflow uses GitHub's OIDC provider to authenticate with AWS (no long-lived secrets):

1. Create an IAM OIDC identity provider for `token.actions.githubusercontent.com`
2. Create an IAM role with trust policy for your repo
3. Set `E2E_AWS_ROLE_ARN` as a repository variable
4. Create a protected environment called `e2e-testing`

### Protected Environment

The `e2e-testing` environment provides:
- Deployment protection rules (optional reviewers for manual triggers)
- Environment-scoped secrets and variables
- Audit trail of deployments

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
├── profiles/                # Profile JSON definitions
│   ├── 01-oidc-cognito-linux-central.json
│   ├── 02-oidc-direct-linux-central-block.json
│   ├── ...
│   └── 12-oidc-cognito-macos-central-alert.json
├── test_auth_flow.py        # Authentication tests
├── test_credential_output.py # Output format tests
├── test_monitoring_pipeline.py # OTLP proxy tests
├── test_quota_enforcement.py # Quota tests
├── test_config_delivery.py  # Bootstrap config tests
├── test_binary_platform.py  # Platform-specific tests
├── artifacts/               # (gitignored) Stack outputs at runtime
└── README.md                # This file
```
