# Claude Code with Bedrock - CLI Reference

This document provides a complete reference for all `ccwb` (Claude Code with Bedrock) commands.

## Table of Contents

- [Claude Code with Bedrock - CLI Reference](#claude-code-with-bedrock---cli-reference)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [Installation](#installation)
  - [Command Reference](#command-reference)
    - [`init` - Configure Deployment](#init---configure-deployment)
    - [`deploy` - Deploy Infrastructure](#deploy---deploy-infrastructure)
    - [`test` - Test Package](#test---test-package)
    - [`package` - Create Distribution](#package---create-distribution)
    - [`builds` - List and Manage CodeBuild Builds](#builds---list-and-manage-codebuild-builds)
    - [`distribute` - Create Distribution URLs](#distribute---create-distribution-urls)
    - [`status` - Check Deployment Status](#status---check-deployment-status)
    - [`cleanup` - Remove Installed Components](#cleanup---remove-installed-components)
    - [`destroy` - Remove Infrastructure](#destroy---remove-infrastructure)

## Overview

The Claude Code with Bedrock CLI (`ccwb`) provides commands for IT administrators to:

- Configure OIDC authentication
- Deploy AWS infrastructure
- Create distribution packages
- Manage deployments

## Installation

```bash
# Clone the repository
git clone [<repository-url>](https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock.git)
cd guidance-for-claude-code-with-amazon-bedrock/source

# Install dependencies
poetry install

# Run commands with poetry
poetry run ccwb <command>
```

## Command Reference

### `init` - Configure Deployment

Creates or updates the configuration for your Claude Code deployment.

```bash
poetry run ccwb init [options]
```

**Options:**

- `--profile <name>` - Configuration profile name (default: "default")

**What it does:**

- Checks prerequisites (AWS CLI, credentials, Python version)
- Prompts for OIDC provider configuration
- Prompts for authentication method selection:
  - Direct IAM: Uses IAM OIDC Provider for federation
  - Cognito: Uses Cognito Identity Pool for federation
- Configures AWS settings (region, stack names)
- Prompts for Claude model selection (Opus, Sonnet, Haiku)
- Configures cross-region inference profiles (US, Europe, APAC)
- Prompts for source region selection for model inference
- Sets up monitoring options
- Prompts for Windows build support via AWS CodeBuild (optional)
- Saves configuration to `.ccwb-config/config.json` in the project directory

**Note:** This command only creates configuration. Use `deploy` to create AWS resources.

### `deploy` - Deploy Infrastructure

Deploys CloudFormation stacks for authentication and monitoring.

```bash
poetry run ccwb deploy [stack] [options]
```

**Arguments:**

- `stack` - Specific stack to deploy: auth, networking, monitoring, dashboard, analytics, or quota (optional)

**Options:**

- `--profile <name>` - Configuration profile to use (default: "default")
- `--dry-run` - Show what would be deployed without executing
- `--show-commands` - Display AWS CLI commands instead of executing

**What it does:**

- Deploys authentication infrastructure (IAM OIDC Provider or Cognito Identity Pool)
- Creates IAM roles and policies for Bedrock access
- Deploys monitoring infrastructure (if enabled)
- Shows stack outputs including authentication resource identifiers

**Stacks deployed:**

1. **auth** - Authentication infrastructure and IAM roles (always required)
2. **networking** - VPC and networking resources for monitoring (optional)
3. **monitoring** - OpenTelemetry collector on ECS Fargate (optional)
4. **dashboard** - CloudWatch dashboard for usage metrics (optional)
5. **analytics** - Kinesis Firehose and Athena for analytics (optional)
6. **quota** - Per-user token quota monitoring and alerts (optional, requires dashboard)
7. **codebuild** - AWS CodeBuild for Windows binary builds (optional, only if enabled during init)

**Examples:**

```bash
# Deploy all configured stacks
poetry run ccwb deploy

# Deploy only authentication
poetry run ccwb deploy auth

# Deploy quota monitoring (requires dashboard stack first)
poetry run ccwb deploy quota

# Show commands without executing
poetry run ccwb deploy --show-commands

# Dry run to see what would be deployed
poetry run ccwb deploy --dry-run
```

> **Note**: Quota monitoring requires the dashboard stack to be deployed first. See [Quota Monitoring Guide](QUOTA_MONITORING.md) for detailed information.

### `test` - Test Package

Tests the packaged distribution as an end user would experience it.

```bash
poetry run ccwb test [options]
```

**Options:**

- `--profile <name>` - AWS profile to test (default: "ClaudeCode")
- `--quick` - Run quick tests only
- `--api` - Test actual Bedrock API calls (costs ~$0.001)

**What it does:**

- Simulates package installation in temporary directory
- Runs the installer script
- Verifies AWS profile configuration
- Tests authentication and IAM role assumption
- Checks Bedrock access in configured regions
- Optionally tests actual API calls to Claude models

**Note:** This command actually installs the package to properly test it.

### `package` - Create Distribution

Creates a distribution package for end users.

```bash
poetry run ccwb package [options]
```

**Options:**

- `--target-platform <platform>` - Target platform for binary (default: "all")
  - `macos` - Build for current macOS architecture
  - `macos-arm64` - Build for Apple Silicon Macs
  - `macos-intel` - Build for Intel Macs (uses Rosetta on ARM Macs)
  - `linux` - Build for Linux (native, current architecture)
  - `linux-x64` - Build for Linux x64 using Docker
  - `linux-arm64` - Build for Linux ARM64 using Docker
  - `windows` - Build for Windows (uses CodeBuild - requires enabling during init)
  - `all` - Build for all available platforms
- `--distribute` - Upload package and generate distribution URL
- `--expires-hours <hours>` - Distribution URL expiration in hours (with --distribute) [default: "48"]
- `--profile <name>` - Configuration profile to use [default: "default"]

**What it does:**

- Builds Nuitka executable from authentication code
- Creates configuration file with:
  - OIDC provider settings
  - Identity Pool ID from deployed stack
  - Credential storage method (keyring or session)
  - Selected Claude model and cross-region profile
  - Source region for model inference
- Generates installer script (install.sh for Unix, install.bat for Windows)
- Creates user documentation
- Optionally uploads to S3 and generates presigned URL (with --distribute)

**Platform Support (Hybrid Build System):**

- **macOS**: Uses PyInstaller with architecture-specific builds
  - ARM64: Native build on Apple Silicon Macs (works on all Macs)
  - Intel: **Optional** - requires x86_64 Python environment on ARM Macs
  - Universal: Requires both architectures' Python libraries (not currently automated)
- **Linux**: Uses PyInstaller in Docker containers
  - x64: Uses linux/amd64 Docker platform
  - ARM64: Uses linux/arm64 Docker platform
  - Docker Desktop handles architecture emulation automatically
- **Windows**: Uses Nuitka via AWS CodeBuild (if enabled during init)
  - Automated builds take 12-15 minutes
  - Requires CodeBuild to be enabled during `init`
  - Will be skipped if CodeBuild is not enabled

**Intel Mac Build Setup (Optional):**

To enable Intel builds on Apple Silicon Macs (optional):

```bash
# Step 1: Install x86_64 Homebrew (if not already installed)
arch -x86_64 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Step 2: Install x86_64 Python
arch -x86_64 /usr/local/bin/brew install python@3.12

# Step 3: Create x86_64 virtual environment
arch -x86_64 /usr/local/bin/python3.12 -m venv ~/venv-x86

# Step 4: Install required packages
arch -x86_64 ~/venv-x86/bin/pip install pyinstaller boto3 keyring
```

**Behavior when Intel environment is not set up:**

- For `--target-platform=all`: Skips Intel builds with a note, builds all other platforms
- For `--target-platform=macos-intel`: Shows instructions for optional setup, skips the build
- The package process continues successfully without Intel binaries
- ARM64 binaries can be distributed to all Mac users (Intel and Apple Silicon)

**Graceful Fallback Behavior:**

The package command is designed to handle missing optional components gracefully:

- **Intel Mac builds**: Skipped if x86_64 Python environment is not available on ARM Macs
- **Windows builds**: Skipped if CodeBuild was not enabled during `init`
- **Linux builds**: Skipped if Docker is not available
- **At least one platform must build successfully** for the package command to succeed

This ensures that packaging always works, even if some optional platforms are not available.

**Output files:**

- `credential-process-<platform>` - Authentication executable
  - `credential-process-macos-arm64` - macOS Apple Silicon
  - `credential-process-macos-intel` - macOS Intel
  - `credential-process-linux-x64` - Linux x64
  - `credential-process-linux-arm64` - Linux ARM64
  - `credential-process-windows.exe` - Windows x64
- `otel-helper-<platform>` - OTEL helper (if monitoring enabled)
- `config.json` - Configuration
- `install.sh` - Unix installer script (auto-detects architecture)
- `install.bat` - Windows installer script
- `README.md` - Installation instructions
- Includes Claude Code telemetry settings (if monitoring enabled)
- Configures environment variables for model selection (ANTHROPIC_MODEL, ANTHROPIC_SMALL_FAST_MODEL)

**Output structure:**

```
dist/
├── credential-process-macos-arm64     # macOS ARM64 executable
├── credential-process-macos-intel     # macOS Intel executable
├── credential-process-linux-x64       # Linux x64 executable
├── credential-process-linux-arm64     # Linux ARM64 executable
├── credential-process-windows.exe     # Windows x64 executable
├── otel-helper-macos-arm64           # macOS ARM64 OTEL helper
├── otel-helper-macos-intel           # macOS Intel OTEL helper
├── otel-helper-linux-x64             # Linux x64 OTEL helper
├── otel-helper-linux-arm64           # Linux ARM64 OTEL helper
├── otel-helper-windows.exe           # Windows OTEL helper
├── config.json                       # Configuration
├── install.sh                        # Unix installer (auto-detects architecture)
├── install.bat                       # Windows installer
├── README.md                         # User instructions
└── .claude/
    └── settings.json                 # Telemetry settings (optional)
```

### `builds` - List and Manage CodeBuild Builds

Shows recent Windows binary builds and their status.

```bash
poetry run ccwb builds [options]
```

**Options:**

- `--limit <n>` - Number of builds to show (default: "10")
- `--project <name>` - CodeBuild project name (default: auto-detect)
- `--status <id>` - Check status of a specific build by ID

**What it does:**

- Lists recent CodeBuild builds for Windows binaries
- Shows build status, duration, and completion time
- Provides console links to view full build logs
- Monitors in-progress builds

**Note:** This command requires CodeBuild to be enabled during the `init` process. If CodeBuild was not enabled, you'll need to re-run `init` and enable Windows build support.

**Example output:**

```
Recent Windows Builds

| Build ID | Status | Started | Duration |
|----------|--------|---------|----------|
| project:abc123 | SUCCEEDED | 2024-08-26 10:15 | 12m 34s |
| project:def456 | IN_PROGRESS | 2024-08-26 10:30 | - |
```

### `distribute` - Create Distribution URLs

Creates secure presigned URLs for package distribution.

```bash
poetry run ccwb distribute [options]
```

**Options:**

- `--expires-hours <hours>` - URL expiration time in hours (1-168) [default: "48"]
- `--get-latest` - Retrieve the latest distribution URL
- `--profile <name>` - Configuration profile to use [default: "default"]

**What it does:**

- Uploads built packages to S3
- Generates presigned URLs for secure distribution
- Stores URLs in Parameter Store for team access
- No AWS credentials required for end users

**Distribution workflow:**

1. Build packages: `poetry run ccwb package --target-platform=all`
2. Create distribution: `poetry run ccwb distribute`
3. Share the generated URL with developers
4. Developers download and run installer without AWS access

**Example:**

```bash
# Build and distribute
poetry run ccwb package --target-platform=all --distribute

# Or separately
poetry run ccwb package --target-platform=all
poetry run ccwb distribute --expires-hours=72

# Get existing URL
poetry run ccwb distribute --get-latest
```

### `status` - Check Deployment Status

Shows the current deployment status and configuration.

```bash
poetry run ccwb status [options]
```

**Options:**

- `--profile <name>` - Profile to check (default: "default")
- `--json` - Output in JSON format
- `--detailed` - Show detailed information

**What it does:**

- Shows current configuration including:
  - Configuration profile and AWS profile names
  - OIDC provider and client ID
  - Selected Claude model and cross-region profile
  - Source region for model inference
  - Analytics and monitoring status
- Checks CloudFormation stack status
- Displays Identity Pool information
- Shows monitoring configuration and endpoints

### `cleanup` - Remove Installed Components

Removes components installed by the test command or manual installation.

```bash
poetry run ccwb cleanup [options]
```

**Options:**

- `--force` - Skip confirmation prompts
- `--profile <name>` - AWS profile name to remove (default: "ClaudeCode")

**What it does:**

- Removes `~/claude-code-with-bedrock/` directory
- Removes AWS profile from `~/.aws/config`
- Removes Claude settings from `~/.claude/settings.json`
- Shows what will be removed before taking action

**Use this to:**

- Clean up after testing
- Remove failed installations
- Start fresh with a new configuration

### `destroy` - Remove Infrastructure

Removes deployed AWS infrastructure.

```bash
poetry run ccwb destroy [stack] [options]
```

**Arguments:**

- `stack` - Specific stack to destroy: auth, networking, monitoring, dashboard, or analytics (optional)

**Options:**

- `--profile <name>` - Configuration profile to use (default: "default")
- `--force` - Skip confirmation prompts

**What it does:**

- Deletes CloudFormation stacks in reverse order (analytics → dashboard → monitoring → networking → auth)
- Shows resources to be deleted before proceeding
- Warns about manual cleanup requirements (e.g., CloudWatch LogGroups)

**Note:** Some resources like CloudWatch LogGroups may require manual deletion.
