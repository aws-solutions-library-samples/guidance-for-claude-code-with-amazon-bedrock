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
- Configures AWS settings (region, identity pool name)
- Prompts for Claude model selection (Opus, Sonnet, Haiku)
- Configures cross-region inference profiles (US, Europe, APAC)
- Prompts for source region selection for model inference
- Sets up monitoring options
- Saves configuration to `.ccwb-config/config.json` in the project directory

**Note:** This command only creates configuration. Use `deploy` to create AWS resources.

### `deploy` - Deploy Infrastructure

Deploys CloudFormation stacks for authentication and monitoring.

```bash
poetry run ccwb deploy [stack] [options]
```

**Arguments:**

- `stack` - Specific stack to deploy: auth, networking, monitoring, dashboard, or analytics (optional)

**Options:**

- `--profile <name>` - Configuration profile to use (default: "default")
- `--dry-run` - Show what would be deployed without executing
- `--show-commands` - Display AWS CLI commands instead of executing

**What it does:**

- Deploys Cognito Identity Pool for authentication
- Creates IAM roles and policies for Bedrock access
- Deploys monitoring infrastructure (if enabled)
- Shows stack outputs including Identity Pool ID

**Stacks deployed:**

1. **auth** - Cognito Identity Pool and IAM roles (always required)
2. **networking** - VPC and networking resources for monitoring (optional)
3. **monitoring** - OpenTelemetry collector on ECS Fargate (optional)
4. **dashboard** - CloudWatch dashboard for usage metrics (optional)
5. **analytics** - Kinesis Firehose and Athena for analytics (optional)

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

- `--target-platform <platform>` - Target platform for binary: macos, linux, or all (default: "all")

**What it does:**

- Builds PyInstaller executable from authentication code
- Creates configuration file with:
  - OIDC provider settings
  - Identity Pool ID from deployed stack
  - Credential storage method (keyring or session)
  - Selected Claude model and cross-region profile
  - Source region for model inference
- Generates installer script
- Creates user documentation
- Includes Claude Code telemetry settings (if monitoring enabled)
- Configures environment variables for model selection (ANTHROPIC_MODEL, ANTHROPIC_SMALL_FAST_MODEL)

**Output structure:**

```
dist/
├── credential-process-macos    # macOS authentication executable
├── credential-process-linux    # Linux authentication executable
├── otel-helper-macos          # macOS OTEL helper (if monitoring enabled)
├── otel-helper-linux          # Linux OTEL helper (if monitoring enabled)
├── config.json                # Configuration
├── install.sh                 # Installation script (auto-detects platform)
├── README.md                  # User instructions
└── .claude/
    └── settings.json          # Telemetry settings (optional)
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
