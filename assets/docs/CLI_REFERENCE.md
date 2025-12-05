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
  - [Quota Management](#quota-management)
    - [`quota set-user` - Set User Quota](#quota-set-user---set-user-quota)
    - [`quota set-group` - Set Group Quota](#quota-set-group---set-group-quota)
    - [`quota set-default` - Set Default Quota](#quota-set-default---set-default-quota)
    - [`quota list` - List Policies](#quota-list---list-policies)
    - [`quota delete` - Delete Policy](#quota-delete---delete-policy)
    - [`quota show` - Show Effective Quota](#quota-show---show-effective-quota)
    - [`quota usage` - Show Usage](#quota-usage---show-usage)
    - [`quota unblock` - Unblock User](#quota-unblock---unblock-user)
    - [`quota export` - Export Policies](#quota-export---export-policies)
    - [`quota import` - Import Policies](#quota-import---import-policies)
  - [Profile Management](#profile-management)
    - [`context list` - List All Profiles](#context-list---list-all-profiles)
    - [`context current` - Show Active Profile](#context-current---show-active-profile)
    - [`context use` - Switch Active Profile](#context-use---switch-active-profile)
    - [`context show` - Display Profile Details](#context-show---display-profile-details)
    - [`config validate` - Validate Profile Configuration](#config-validate---validate-profile-configuration)
    - [`config export` - Export Profile Configuration](#config-export---export-profile-configuration)
    - [`config import` - Import Profile Configuration](#config-import---import-profile-configuration)
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

- `--profile <name>` - Configuration profile name (optional, will prompt if not specified)

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
- Configures quota monitoring:
  - Monthly token limit per user
  - Daily token limit with burst buffer (auto-calculated from monthly)
  - Enforcement modes (alert vs block) for daily and monthly limits
  - Quota re-check interval (how often to verify quota with cached credentials)
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

#### When to Use `ccwb deploy` vs `ccwb deploy quota`

| Command | Use Case |
|---------|----------|
| `ccwb deploy` | Initial setup - deploys all enabled stacks including quota (when enabled) |
| `ccwb deploy quota` | Update quota settings, late enablement, or troubleshooting |

**When `ccwb deploy` deploys quota**: If `quota_monitoring_enabled=True` in your profile (set during `ccwb init`), running `ccwb deploy` will automatically deploy the quota stack as part of the full deployment.

**When to use `ccwb deploy quota`**:
- You want to update quota configuration without redeploying other stacks
- You initially deployed without quota and now want to add it
- You need to troubleshoot or redeploy just the quota stack
- Your organization requires phased deployments with explicit control

### `test` - Test Package

Tests the packaged distribution as an end user would experience it.

```bash
poetry run ccwb test [options]
```

**Options:**

- `--profile, -p <name>` - Profile name to test (defaults to active profile)
- `--full` - Test all allowed regions (default: tests 3 representative regions)
- `--quota-only` - Run only quota monitoring tests (API, policies, usage capture)
- `--quota-api <endpoint>` - Test quota API with optional custom endpoint override

**What it does:**

- Finds the latest package for the profile in `dist/{profile}/{timestamp}/`
- Verifies package contents (binary, config, OTEL helper)
- Tests credential process binary execution
- Tests authentication and IAM role assumption
- Tests Bedrock API access in configured regions
- Tests inference profile availability
- Tests quota monitoring API (if enabled)

**Quota Testing (`--quota-only`):**

When using `--quota-only`, runs comprehensive quota monitoring tests:

1. **Quota Config** - Validates all quota configuration is present
2. **Quota API** - Tests the `/check` endpoint with JWT authentication
3. **Create Policy** - Creates a test user policy in DynamoDB
4. **List Policies** - Verifies the policy appears in the list
5. **Resolve Quota** - Tests policy resolution for users
6. **Delete Policy** - Cleans up the test policy

**Examples:**

```bash
# Run standard tests
poetry run ccwb test

# Run only quota monitoring tests (fastest for quota validation)
poetry run ccwb test --quota-only

# Test quota API against a staging endpoint
poetry run ccwb test --quota-only --quota-api https://staging-api.example.com/prod

# Run all tests with custom quota endpoint
poetry run ccwb test --quota-api https://my-api.execute-api.us-east-1.amazonaws.com/prod
```

**Note:** API tests run by default and make actual calls to Bedrock (minimal cost ~$0.001).

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

- `--profile <name>` - Configuration profile to use (defaults to active profile)
- `--limit <n>` - Number of builds to show (default: "10")
- `--project <name>` - CodeBuild project name (default: auto-detect)
- `--status <id>` - Check status of a specific build by ID
- `--download` - Download completed Windows artifacts to dist folder

**What it does:**

- Lists recent CodeBuild builds for Windows binaries
- Shows build status, duration, and completion time
- Provides console links to view full build logs
- Monitors in-progress builds
- Uses active profile or specified profile for CodeBuild project detection

**Note:** This command requires CodeBuild to be enabled during the `init` process. If CodeBuild was not enabled, you'll need to re-run `init` and enable Windows build support.

**Examples:**

```bash
# List builds for active profile
poetry run ccwb builds

# List builds for specific profile
poetry run ccwb builds --profile production

# Check status of specific build
poetry run ccwb builds --status abc12345

# Check latest build status and download artifacts
poetry run ccwb builds --status latest --download

# List last 20 builds
poetry run ccwb builds --limit 20
```

**Example output:**

```
Recent Windows Builds

| Build ID | Status | Started | Duration |
|----------|--------|---------|----------|
| project:abc123 | SUCCEEDED | 2024-08-26 10:15 | 12m 34s |
| project:def456 | IN_PROGRESS | 2024-08-26 10:30 | - |
```

### `distribute` - Share Packages via Distribution

Upload and distribute built packages via presigned S3 URLs or authenticated landing page.

```bash
poetry run ccwb distribute [options]
```

**Options:**

- `--expires-hours <hours>` - URL expiration time in hours (1-168) [default: "48"]
- `--get-latest` - Retrieve the latest distribution URL (presigned-s3 only)
- `--profile <name>` - Configuration profile to use (uses active profile if not specified)
- `--package-path <path>` - Path to package directory [default: "dist"]
- `--build-profile <name>` - Select build by profile name
- `--timestamp <timestamp>` - Select build by timestamp (format: YYYY-MM-DD-HHMMSS)
- `--latest` - Auto-select latest build without wizard
- `--allowed-ips <ranges>` - Comma-separated IP ranges for access control (presigned-s3 only)
- `--show-qr` - Display QR code for URL (requires qrcode library)

**What it does:**

Behavior depends on your configured distribution type:

**Presigned S3 URLs (Simple):**
- Uploads packages to S3 bucket
- Generates secure presigned URLs (default 48 hours)
- Stores URLs in Parameter Store for team access
- Share URLs via email/Slack
- No authentication required for downloads

**Landing Page (Enterprise):**
- Uploads platform-specific packages (windows/linux/mac/all-platforms)
- Updates S3 metadata (profile, timestamp, release date)
- Provides landing page URL for authenticated access
- Users authenticate via IdP (Okta/Azure/Auth0/Cognito)
- Platform auto-detection and recommendations

**Distribution workflow:**

1. Build packages: `poetry run ccwb package`
2. Upload and distribute: `poetry run ccwb distribute`
3. **Presigned-s3**: Share generated URLs with developers
4. **Landing-page**: Direct users to your landing page URL

**Examples:**

```bash
# Distribute latest build (interactive build selection)
poetry run ccwb distribute

# Distribute latest build automatically (skip wizard)
poetry run ccwb distribute --latest

# Distribute specific build by timestamp
poetry run ccwb distribute --timestamp 2024-11-14-083022

# Distribute with custom expiration (presigned-s3 only)
poetry run ccwb distribute --expires-hours=72

# Get existing URL without re-uploading (presigned-s3 only)
poetry run ccwb distribute --get-latest

# Distribute with QR code for mobile sharing
poetry run ccwb distribute --show-qr
```

**Build Selection:**

If you have multiple builds in `dist/`, the command will:
1. Scan for organized profile/timestamp builds
2. Show interactive wizard to select which build to distribute
3. Display build date, size, and platforms included
4. Allow selection by profile name or timestamp

Use `--latest` to skip the wizard and auto-select the most recent build.

**Platform-Specific Uploads (Landing Page):**

For landing-page distribution, packages are organized by platform:
- `packages/windows/latest.zip` - Windows package
- `packages/linux/latest.zip` - Linux package
- `packages/mac/latest.zip` - macOS package
- `packages/all-platforms/latest.zip` - All platforms bundle

Landing page auto-detects user's OS and recommends appropriate package.

### `status` - Check Deployment Status

Shows the current deployment status and configuration.

```bash
poetry run ccwb status [options]
```

**Options:**

- `--profile <name>` - Profile to check (uses active profile if not specified)
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

## Quota Management

Commands for managing per-user and group token quotas. Requires quota monitoring to be enabled during `init`.

For detailed architecture and configuration, see [QUOTA_MONITORING.md](QUOTA_MONITORING.md).

### `quota set-user` - Set User Quota

Sets a quota policy for a specific user.

```bash
poetry run ccwb quota set-user <email> [options]
```

**Arguments:**
- `<email>` - User's email address

**Options:**
- `--monthly-limit, -m <tokens>` - Monthly token limit (supports K, M, B suffixes: 10M = 10,000,000)
- `--daily-limit, -d <tokens>` - Daily token limit (optional)
- `--enforcement, -e <mode>` - Enforcement mode: `alert` (monitor only) or `block` (deny access)
- `--disabled` - Create policy in disabled state
- `--profile, -p <name>` - Configuration profile

**Example:**
```bash
poetry run ccwb quota set-user alice@example.com -m 5M -e block
```

### `quota set-group` - Set Group Quota

Sets a quota policy for a group (applies to all users in the group).

```bash
poetry run ccwb quota set-group <group> [options]
```

**Arguments:**
- `<group>` - Group name (from OIDC groups claim)

**Options:**
- Same as `set-user`

**Example:**
```bash
poetry run ccwb quota set-group engineering -m 20M -d 1M -e alert
```

### `quota set-default` - Set Default Quota

Sets the default quota policy for all users without a specific user or group policy.

```bash
poetry run ccwb quota set-default [options]
```

**Options:**
- Same as `set-user`

**Example:**
```bash
poetry run ccwb quota set-default -m 225M -e alert
```

### `quota list` - List Policies

Lists all quota policies.

```bash
poetry run ccwb quota list [options]
```

**Options:**
- `--type <type>` - Filter by type: `user`, `group`, or `default`
- `--profile, -p <name>` - Configuration profile

### `quota delete` - Delete Policy

Deletes a quota policy.

```bash
poetry run ccwb quota delete <type> <identifier> [options]
```

**Arguments:**
- `<type>` - Policy type: `user`, `group`, or `default`
- `<identifier>` - Email (for user), group name, or "default"

**Options:**
- `--profile, -p <name>` - Configuration profile

**Example:**
```bash
poetry run ccwb quota delete user alice@example.com
```

### `quota show` - Show Effective Quota

Shows the effective quota policy for a user (resolves user > group > default precedence).

```bash
poetry run ccwb quota show <email> [options]
```

**Arguments:**
- `<email>` - User's email address

**Options:**
- `--profile, -p <name>` - Configuration profile

### `quota usage` - Show Usage

Shows current usage against quota limits for a user.

```bash
poetry run ccwb quota usage <email> [options]
```

**Arguments:**
- `<email>` - User's email address

**Options:**
- `--profile, -p <name>` - Configuration profile

### `quota unblock` - Unblock User

Temporarily unblocks a user who has been blocked due to quota exceeded.

```bash
poetry run ccwb quota unblock <email> [options]
```

**Arguments:**
- `<email>` - User's email address

**Options:**
- `--duration <time>` - Duration: `24h`, `7d`, `until-reset`, or custom (e.g., `48h`, `3d`)
- `--reason <text>` - Reason for unblock (for audit trail)
- `--profile, -p <name>` - Configuration profile

**Example:**
```bash
poetry run ccwb quota unblock alice@example.com --duration 24h --reason "Emergency project deadline"
```

### `quota export` - Export Policies

Exports quota policies to a JSON or CSV file for backup, migration, or auditing.

```bash
poetry run ccwb quota export <file> [options]
```

**Arguments:**
- `<file>` - Output file path (.json or .csv)

**Options:**
- `--type, -t <type>` - Filter by policy type: `user`, `group`, or `default`
- `--stdout` - Output to stdout instead of file
- `--profile, -p <name>` - Configuration profile

**Examples:**
```bash
# Export all policies to JSON
poetry run ccwb quota export policies.json

# Export to CSV for spreadsheet editing
poetry run ccwb quota export policies.csv

# Export only user policies
poetry run ccwb quota export users.json --type user

# Export to stdout (for piping)
poetry run ccwb quota export --stdout > backup.json
```

**JSON output format:**
```json
{
  "version": "1.0",
  "exported_at": "2025-11-29T10:30:00Z",
  "policies": [
    {
      "type": "user",
      "identifier": "alice@example.com",
      "monthly_token_limit": "300M",
      "daily_token_limit": "15M",
      "enforcement_mode": "alert",
      "enabled": true
    }
  ]
}
```

**CSV output format:**
```csv
type,identifier,monthly_token_limit,daily_token_limit,enforcement_mode,enabled
user,alice@example.com,300M,15M,alert,true
group,engineering,500M,25M,block,true
default,default,225M,8M,alert,true
```

### `quota import` - Import Policies

Imports quota policies from a JSON or CSV file. Supports bulk policy creation with conflict handling.

```bash
poetry run ccwb quota import <file> [options]
```

**Arguments:**
- `<file>` - Input file path (.json or .csv)

**Options:**
- `--skip-existing` - Skip policies that already exist
- `--update` - Update existing policies (upsert mode)
- `--dry-run` - Preview changes without applying
- `--type, -t <type>` - Import only specific type: `user`, `group`, or `default`
- `--auto-daily` - Auto-calculate daily limits for policies missing `daily_token_limit`
- `--burst <percent>` - Burst buffer percentage for auto-daily calculation (default: 10)
- `--profile, -p <name>` - Configuration profile

**Examples:**
```bash
# Import from JSON, skip existing policies
poetry run ccwb quota import policies.json --skip-existing

# Import from CSV, update existing policies
poetry run ccwb quota import policies.csv --update

# Preview import without making changes
poetry run ccwb quota import policies.json --dry-run

# Import users only
poetry run ccwb quota import all-policies.csv --type user --update

# Auto-calculate daily limits with 15% burst buffer
poetry run ccwb quota import users.csv --auto-daily --burst 15
```

**Output example:**
```
✓ Created: alice@example.com (user) - 300M
✓ Created: bob@example.com (user) - 200M
⚠ Skipped: engineering (group) - already exists
✓ Updated: ml-team (group) - 1B

Import Summary
  Created: 2
  Updated: 1
  Skipped: 1
  Errors:  0
```

**Required CSV columns:**
- `type` - Policy type: `user`, `group`, or `default`
- `identifier` - User email, group name, or `default`
- `monthly_token_limit` - Monthly limit (supports K/M/B suffix, e.g., `300M`)

**Optional CSV columns:**
- `daily_token_limit` - Daily limit (auto-calculated if `--auto-daily`)
- `enforcement_mode` - `alert` (default) or `block`
- `enabled` - `true` (default) or `false`

## Profile Management

The following commands manage multiple deployment profiles (v2.0+). Profiles let you manage configurations for different AWS accounts, regions, or organizations from a single machine.

### `context list` - List All Profiles

Shows all available profiles with an indicator for the active profile.

```bash
poetry run ccwb context list
```

**What it does:**

- Lists all profiles in `~/.ccwb/profiles/`
- Displays profile name, AWS region, and stack name
- Highlights the currently active profile
- Shows profile count

**Example output:**

```
Available Profiles:
  * production (us-east-1, stack: claude-code-prod)
    development (us-west-2, stack: claude-code-dev)
    eu-deployment (eu-west-1, stack: claude-code-eu)

Active profile: production
Total profiles: 3
```

### `context current` - Show Active Profile

Displays the currently active profile name.

```bash
poetry run ccwb context current
```

**What it does:**

- Shows the name of the active profile
- Exits with error if no active profile is set

**Example output:**

```
Current profile: production
```

### `context use` - Switch Active Profile

Changes the active profile to the specified one.

```bash
poetry run ccwb context use <profile-name>
```

**Arguments:**

- `profile-name` - Name of the profile to activate (required)

**What it does:**

- Sets the specified profile as active
- Validates that the profile exists
- Updates global configuration file

**Examples:**

```bash
# Switch to production profile
poetry run ccwb context use production

# Switch to development profile
poetry run ccwb context use development
```

### `context show` - Display Profile Details

Shows detailed configuration for a profile.

```bash
poetry run ccwb context show [profile-name]
```

**Arguments:**

- `profile-name` - Profile to display (optional, defaults to active profile)

**Options:**

- `--json` - Output in JSON format

**What it does:**

- Displays full profile configuration including:
  - AWS region and account
  - OIDC provider settings
  - Stack names
  - Model selection
  - Monitoring configuration
- Masks sensitive values (client secrets)

**Examples:**

```bash
# Show active profile details
poetry run ccwb context show

# Show specific profile
poetry run ccwb context show production

# Output as JSON
poetry run ccwb context show --json
```

### `config validate` - Validate Profile Configuration

Validates profile configuration for errors.

```bash
poetry run ccwb config validate [profile-name|all]
```

**Arguments:**

- `profile-name` - Profile to validate (optional, defaults to active profile)
- `all` - Validate all profiles

**What it does:**

- Checks required fields are present
- Validates field formats (region, stack names, URLs)
- Verifies AWS credentials exist
- Reports validation errors with suggestions

**Examples:**

```bash
# Validate active profile
poetry run ccwb config validate

# Validate specific profile
poetry run ccwb config validate production

# Validate all profiles
poetry run ccwb config validate all
```

### `config export` - Export Profile Configuration

Exports a profile configuration to a file (sanitized).

```bash
poetry run ccwb config export [profile-name] [options]
```

**Arguments:**

- `profile-name` - Profile to export (optional, defaults to active profile)

**Options:**

- `--output <file>` - Output file path (default: `<profile-name>.json`)
- `--include-secrets` - Include sensitive values (not recommended)

**What it does:**

- Exports profile configuration to JSON file
- Removes sensitive values by default (client secrets)
- Creates portable configuration file

**Examples:**

```bash
# Export active profile (secrets removed)
poetry run ccwb config export

# Export specific profile to custom path
poetry run ccwb config export production --output prod-config.json

# Export with secrets (use caution)
poetry run ccwb config export --include-secrets
```

### `config import` - Import Profile Configuration

Imports a profile configuration from a file.

```bash
poetry run ccwb config import <file> [name]
```

**Arguments:**

- `file` - Path to configuration file (required)
- `name` - Name for imported profile (optional, uses name from file)

**Options:**

- `--overwrite` - Overwrite if profile already exists
- `--set-active` - Set as active profile after import

**What it does:**

- Imports profile configuration from JSON file
- Validates configuration before importing
- Creates new profile in `~/.ccwb/profiles/`
- Optionally sets as active profile

**Examples:**

```bash
# Import profile with default name
poetry run ccwb config import prod-config.json

# Import with custom name
poetry run ccwb config import config.json staging

# Import and set as active
poetry run ccwb config import config.json --set-active

# Overwrite existing profile
poetry run ccwb config import config.json production --overwrite
```

### `destroy` - Remove Infrastructure

Removes deployed AWS infrastructure.

```bash
poetry run ccwb destroy [stack] [options]
```

**Arguments:**

- `stack` - Specific stack to destroy: auth, networking, monitoring, dashboard, or analytics (optional)

**Options:**

- `--profile <name>` - Configuration profile to use (uses active profile if not specified)
- `--force` - Skip confirmation prompts

**What it does:**

- Deletes CloudFormation stacks in reverse order (analytics → dashboard → monitoring → networking → auth)
- Shows resources to be deleted before proceeding
- Warns about manual cleanup requirements (e.g., CloudWatch LogGroups)

**Note:** Some resources like CloudWatch LogGroups may require manual deletion.
