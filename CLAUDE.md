# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start (AI-Assisted)

New to this repo? Use these slash commands in Claude Code:

- `/setup` — Set up your development environment (checks Python, installs deps, runs smoke tests)
- `/validate` — Run all checks: linting, formatting, CloudFormation validation, smoke tests
- `/test [path]` — Run tests with coverage and get plain-English explanations of failures
- `/troubleshoot [env|auth|deploy|tests]` — Diagnose common issues
- `/add-command <name>` — Scaffold a new CLI command with boilerplate and tests
- `/add-provider <name>` — Scaffold support for a new identity provider (IdP)
- `/check-cfn [template]` — Deep-validate CloudFormation templates

Three specialized agents are also available and will be used automatically when relevant:
- **cfn-expert** — CloudFormation template specialist (multi-partition, IAM, cross-stack)
- **auth-expert** — OIDC/OAuth2 authentication flow specialist
- **test-runner** — Test execution and failure analysis specialist

## Project Overview

This is an AWS Guidance solution for deploying Claude Code with Amazon Bedrock in enterprise environments. It provides enterprise authentication patterns using OIDC identity federation (Okta, Azure AD, Auth0, Cognito User Pools) to enable centralized access control and audit trails for Claude Code usage.

The solution consists of three main Python packages:
- **claude_code_with_bedrock**: Admin CLI (`ccwb`) for deployment and management
- **credential_provider**: OAuth2/OIDC credential process for end users (packaged as standalone executable)
- **otel_helper**: OpenTelemetry helper for extracting user attributes from JWT tokens (optional)

## Essential Commands

### Development Setup
```bash
# Install dependencies (from source/ directory)
cd source
poetry install

# Install pre-commit hooks
poetry run pre-commit install
```

### Primary CLI Commands
All commands run from `source/` directory with `poetry run`:

```bash
# Initialize configuration (interactive wizard)
poetry run ccwb init

# Deploy CloudFormation infrastructure
poetry run ccwb deploy

# Build distribution packages for all platforms
poetry run ccwb package --target-platform all

# Check Windows build status (runs in AWS CodeBuild)
poetry run ccwb builds

# Test authentication and Bedrock access
poetry run ccwb test

# Create distribution (presigned URLs or upload to landing page)
poetry run ccwb distribute

# View deployment status
poetry run ccwb status

# Cleanup all AWS resources
poetry run ccwb destroy

# Manage profiles (multiple deployments)
poetry run ccwb context list
poetry run ccwb context use <profile-name>
poetry run ccwb context show
```

### Testing
```bash
# Run all tests (from source/ directory)
poetry run pytest

# Run specific test categories
poetry run pytest tests/cli/commands/  # CLI command tests
poetry run pytest tests/test_models.py # Model configuration tests
poetry run pytest tests/test_cloudformation.py  # CloudFormation validation
poetry run pytest tests/test_smoke.py  # Quick smoke tests

# Run with coverage
poetry run pytest --cov=claude_code_with_bedrock --cov-report=term-missing

# Run pre-commit checks manually
poetry run pre-commit run --all-files
```

### Code Quality
```bash
# Lint Python code with Ruff
poetry run ruff check source/

# Format Python code with Ruff
poetry run ruff format source/

# Validate CloudFormation templates
poetry run cfn-lint deployment/infrastructure/*.yaml
```

## Architecture

### Component Overview

**Authentication Flow:**
1. User requests AWS credentials → AWS CLI invokes credential process executable
2. Credential process initiates OAuth2 PKCE flow with IdP
3. User authenticates via browser with corporate credentials
4. IdP returns authorization code → exchanged for OIDC tokens
5. Tokens federated to temporary AWS credentials via IAM OIDC Provider or Cognito Identity Pool
6. Credentials returned to Claude Code with session tags (user email, subject) for CloudTrail attribution

**Key Components:**
- `source/claude_code_with_bedrock/`: Admin CLI built on Cleo framework for infrastructure management
- `source/credential_provider/`: Standalone OAuth2/OIDC client implementing AWS CLI credential process protocol
- `source/otel_helper/`: JWT decoder for extracting user attributes for OpenTelemetry telemetry
- `deployment/infrastructure/`: CloudFormation templates for auth, monitoring, distribution, and analytics
- `source/claude_code_with_bedrock/models.py`: Single source of truth for Claude model IDs and cross-region profiles
- `source/claude_code_with_bedrock/config.py`: Profile configuration management (stored in `~/.ccwb/`)

### Federation Methods

**Direct IAM Federation** (Recommended):
- IAM OIDC Provider + STS AssumeRoleWithWebIdentity
- Configurable session duration up to 12 hours
- Lower latency, simpler architecture

**Cognito Identity Pool**:
- Amazon Cognito federates OIDC tokens to AWS credentials
- Configurable session duration up to 8 hours
- Supports legacy IdPs without direct OIDC support

Both methods provide full CloudTrail attribution via session tags containing user email and subject.

### CloudFormation Stacks

Located in `deployment/infrastructure/`:
- `bedrock-auth-*.yaml`: Identity federation (Direct IAM or Cognito) for different IdP types
- `cognito-identity-pool.yaml`: Cognito Identity Pool federation (alternative method)
- `otel-collector.yaml`: OpenTelemetry collector on ECS Fargate with ALB
- `networking.yaml`: VPC and networking resources for monitoring
- `metrics-aggregation.yaml`: DynamoDB table for metrics storage
- `claude-code-dashboard.yaml`: CloudWatch dashboard for usage analytics
- `analytics-pipeline.yaml`: Kinesis Firehose + S3 + Athena for long-term analytics
- `quota-monitoring.yaml`: User quota limits and alerting
- `landing-page-distribution.yaml`: Authenticated landing page for package downloads
- `presigned-s3-distribution.yaml`: S3 bucket for presigned URL distribution
- `codebuild-windows.yaml`: CodeBuild project for Windows executable compilation

### Package Building

The `ccwb package` command creates platform-specific executables:
- **macOS**: PyInstaller builds (ARM64, Intel, or Universal2)
- **Linux**: Docker-based PyInstaller builds (x86_64, ARM64)
- **Windows**: AWS CodeBuild with Nuitka compilation (runs async in background)

Distribution package (`dist/`) includes:
- Platform-specific credential process executables
- `install.sh` / `install.bat` installers
- `config.json` with embedded deployment configuration
- `.claude/settings.json` for OpenTelemetry integration (if monitoring enabled)
- OTEL helper executables (if monitoring enabled)

### Configuration Management

**Profile Storage**: `~/.ccwb/` (migrated from `source/.ccwb-config/` in v2.0)
- `config.json`: All profile configurations
- `context.json`: Active profile tracking

**Profile Structure** (`source/claude_code_with_bedrock/config.py`):
- Provider settings (domain, client ID, provider type)
- AWS region and identity pool configuration
- Cross-region inference profile and model selection
- Monitoring/analytics settings
- Distribution configuration
- Stack names for deployed CloudFormation stacks

## Important Patterns

### Model Configuration
- All Claude model definitions live in `source/claude_code_with_bedrock/models.py`
- Cross-region profiles: `us`, `europe`, `apac`, `us-gov`
- Model IDs follow pattern: `{profile}.anthropic.{model}-{date}-v{version}:0`
- Source regions: where requests originate (for AWS profile configuration)
- Destination regions: where Bedrock routes inference requests

### Multi-Partition Support
- Same codebase supports AWS Commercial and AWS GovCloud (US)
- CloudFormation uses `${AWS::Partition}` pseudo-parameter for ARNs
- Service principals are region-specific in GovCloud (e.g., `cognito-identity-us-gov.amazonaws.com`)
- GovCloud model IDs use `us-gov.` prefix

### Credential Storage Options
- **keyring**: OS-native secure storage (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- **session**: Encrypted files in `~/.aws/` with restricted permissions

### Distribution Methods
Three options configured during `ccwb init`:
1. **Manual**: Zip and share `dist/` folder via email/file sharing
2. **Presigned S3**: Time-limited S3 URLs (default 48h expiry)
3. **Landing Page**: Authenticated web portal with IdP SSO and platform auto-detection

## Testing Guidance

### Test Organization
- `tests/cli/commands/`: CLI command tests (init, deploy, package)
- `tests/test_*.py`: Core functionality tests (models, config, CloudFormation)
- `tests/conftest.py`: Shared fixtures and AWS region configuration

### Test Execution Notes
- Always run tests from `source/` directory
- Pre-commit hooks run smoke tests automatically
- Lambda tests have module isolation issues - run separately by file for best results
- CloudFormation validation tests require valid templates in `deployment/infrastructure/`

### Mock Patterns
Tests heavily mock AWS services (boto3 clients) and filesystem operations. Key patterns:
- Use `@patch("boto3.client")` for AWS service mocks
- Use `tmp_path` fixture for file system isolation
- Mock questionary for interactive CLI tests
- Mock CloudFormation outputs for stack lookups

## Development Workflow

### Making Changes
1. Create feature branch from `main`
2. Make changes in appropriate module (`claude_code_with_bedrock/`, `credential_provider/`, etc.)
3. Add/update tests in `tests/`
4. Run pre-commit hooks: `poetry run pre-commit run --all-files`
5. Run relevant tests: `poetry run pytest tests/path/to/test_*.py`
6. Update CloudFormation templates if infrastructure changes
7. Validate templates: `poetry run cfn-lint deployment/infrastructure/*.yaml`
8. Create pull request to `main` branch

### CloudFormation Template Development
- Templates use YAML format (converted to JSON during deployment via cfn-flip)
- Validate with cfn-lint: `poetry run cfn-lint deployment/infrastructure/*.yaml`
- Test locally: `poetry run ccwb test --local` (uses mocked AWS services)
- Templates support both AWS Commercial and GovCloud via `${AWS::Partition}` parameter

### Adding New Commands
1. Create command class in `source/claude_code_with_bedrock/cli/commands/`
2. Inherit from `cleo.commands.Command`
3. Register in `source/claude_code_with_bedrock/cli/__init__.py`
4. Add tests in `tests/cli/commands/test_<command>.py`
5. Update CLI_REFERENCE.md documentation

### Adding New IdP Providers
1. Add provider detection logic in `source/claude_code_with_bedrock/validators.py`
2. Create CloudFormation template: `deployment/infrastructure/bedrock-auth-<provider>.yaml`
3. Update `source/claude_code_with_bedrock/cli/commands/init.py` wizard
4. Add provider-specific documentation in `assets/docs/providers/<provider>-setup.md`
5. Update `source/credential_provider/__main__.py` for any provider-specific OAuth logic

## Common Issues

### Windows Build Failures
- Windows builds run in AWS CodeBuild and take 20+ minutes
- Check status: `poetry run ccwb builds`
- CodeBuild must be enabled during `ccwb init`
- If not enabled, package command skips Windows and continues with other platforms

### Authentication Issues
- Force re-authentication: `~/claude-code-with-bedrock/credential-process --clear-cache`
- Check profile configuration: `poetry run ccwb context show`
- Verify IdP application configuration (redirect URI must be `http://localhost:8400/callback`)

### Stack Deployment Failures
- View status: `poetry run ccwb status`
- Check CloudFormation console for detailed error messages
- Common issues: IAM permissions, Bedrock not activated in region, invalid IdP configuration

### Test Failures
- Ensure running from `source/` directory
- Check AWS region is set (done automatically via `tests/conftest.py`)
- Lambda tests may fail when run together - run by file instead
- Pre-commit hooks provide fast feedback before full test suite

## Key Files Reference

- `source/pyproject.toml`: Poetry dependencies and tool configuration
- `source/claude_code_with_bedrock/cli/__init__.py`: CLI application entry point
- `source/claude_code_with_bedrock/config.py`: Profile and configuration data models
- `source/claude_code_with_bedrock/models.py`: Claude model definitions and cross-region profiles
- `source/claude_code_with_bedrock/validators.py`: Input validation and provider detection
- `source/credential_provider/__main__.py`: OAuth2/OIDC authentication implementation
- `.pre-commit-config.yaml`: Linting and validation hooks
- `deployment/infrastructure/`: All CloudFormation templates
- `tests/conftest.py`: Shared test fixtures and configuration
