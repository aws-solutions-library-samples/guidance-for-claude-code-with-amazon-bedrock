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

- Existing OIDC identity provider (Okta, Azure AD, Auth0, etc.)
- Ability to create OIDC applications
- Redirect URI support for `http://localhost:8400/callback`

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

The wizard will guide you through:

- OIDC provider configuration (domain, client ID)
- AWS region selection for infrastructure
- Amazon Bedrock cross-region inference configuration
- Credential storage method (keyring or session files)
- Optional monitoring setup with VPC configuration

#### Understanding Profiles (v2.0+)

**What are profiles?** Profiles let you manage multiple deployments from one machine (different AWS accounts, regions, or organizations).

**Common use cases:**
- Production vs development accounts
- US vs EU regional deployments
- Multiple customer/tenant deployments

**Profile commands:**
- `ccwb context list` - See all profiles
- `ccwb context use <name>` - Switch between profiles
- `ccwb context show` - View active profile details

See [CLI Reference](assets/docs/CLI_REFERENCE.md) for complete command list.

**Upgrading from v1.x:** Profile configuration automatically migrates from `source/.ccwb-config/` to `~/.ccwb/` on first run. Your profile names and active profile are preserved. A timestamped backup is created automatically.

### Step 3: Deploy Infrastructure

Deploy the AWS CloudFormation stacks:

```bash
poetry run ccwb deploy
```

This creates the following AWS resources:

**Authentication Infrastructure:**

- IAM OIDC Provider or Amazon Cognito Identity Pool for OIDC federation
- IAM trust relationship for federated access
- IAM role with policies for:
  - Bedrock model invocation in specified regions
  - CloudWatch metrics (if monitoring enabled)

**Optional Monitoring Infrastructure:**

- VPC and networking resources (or integration with existing VPC)
- ECS Fargate cluster running OpenTelemetry collector
- Application Load Balancer for OTLP ingestion
- CloudWatch Log Groups and Metrics
- CloudWatch Dashboard with comprehensive usage analytics
- DynamoDB table for metrics aggregation and storage
- Lambda functions for custom dashboard widgets
- Kinesis Data Firehose for streaming metrics to S3 (if analytics enabled)
- Amazon Athena for SQL analytics on collected metrics (if analytics enabled)
- S3 bucket for long-term metrics storage (if analytics enabled)

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
- Uses Docker for cross-platform Linux builds when running on macOS
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
- **Linux**: Docker with PyInstaller (for building on non-Linux hosts)

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

### Authentication Issues

Force re-authentication:

```bash
~/claude-code-with-bedrock/credential-process --clear-cache
```

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
