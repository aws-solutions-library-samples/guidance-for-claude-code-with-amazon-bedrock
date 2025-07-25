# Guidance for Claude Code with Amazon Bedrock

This solution enables organizations to provide secure, centralized access to Claude models through Amazon Bedrock using existing enterprise identity providers. By integrating with OIDC providers like Okta, Azure AD, and Auth0, organizations can maintain their current authentication workflows while giving users seamless access to Claude Code without managing individual API keys.

## Key Features

### For Organizations

- **Enterprise SSO Integration**: Leverage existing OIDC identity providers (Okta, Azure AD, Auth0, etc.)
- **Centralized Access Control**: Manage Claude Code access through your identity provider
- **No API Key Management**: Eliminate the need to distribute or rotate long-lived credentials
- **Comprehensive Audit Trail**: Full CloudTrail logging of all Bedrock access
- **Usage Monitoring**: Optional CloudWatch dashboards for tracking usage and costs
- **Multi-Region Support**: Configure which AWS regions users can access Bedrock in

### For End Users

- **Seamless Authentication**: Log in with corporate credentials
- **Automatic Credential Refresh**: No manual token management required
- **AWS CLI/SDK Integration**: Works with any AWS tool or SDK
- **Secure Credential Storage**: Choice of OS keyring or session-based storage
- **Multi-Profile Support**: Manage multiple authentication profiles

## Table of Contents

1. [Quick Start](#quick-start)
2. [Enterprise Authentication Pattern](#enterprise-authentication-pattern)
3. [Architecture Overview](#architecture-overview)
4. [Prerequisites](#prerequisites)
5. [Implementation](#implementation)
6. [End User Experience](#end-user-experience)
7. [Monitoring and Operations](#monitoring-and-operations)
8. [Best Practices](#best-practices)
9. [CLI Commands](#cli-commands)
10. [Additional Resources](#additional-resources)

## Quick Start

### Prerequisites

See [Prerequisites](#prerequisites) including setting up [supported OIDC providers](#supported-oidc-providers).

### Getting started

1. Deploy solution resources to your AWS account by executing the commands below.

```bash
# Clone the repository
git clone https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock
cd guidance-for-claude-code-with-amazon-bedrock/source

# Install dependencies
poetry install

# Run interactive setup wizard
poetry run ccwb init

# Deploy infrastructure
poetry run ccwb deploy

# Create distribution package for users
poetry run ccwb package
```

2. Test package locally to verify end-user installation and access to Amazon Bedrock.

```
# Test package locally
poetry run ccwb test
```

3. [Distribute](#end-user-experience) package to end-users.

### Cleanup

You are responsible for the [costs](#cost) of AWS services while running this solution. If you decide that you no longer need the solution, please ensure that infrastructure resources are removed.

```
poetry run ccwb destroy
```

## How it works

This solution implements an Enterprise Authentication Pattern that enables organizations to securely integrate Claude Code with their existing identity infrastructure. The pattern provides:

- **OIDC Identity Provider Integration**: Seamless authentication through Okta, Azure AD, Auth0, and other OIDC-compliant providers
- **Temporary AWS Credentials**: Eliminates long-lived credentials by providing session-based access to Amazon Bedrock
- **Centralized Access Control**: Manage Claude Code access through your existing identity provider groups and policies
- **Comprehensive Audit Logging**: Full CloudTrail integration for compliance and security monitoring
- **Optional Usage Monitoring**: CloudWatch dashboards and metrics for tracking Claude Code usage across your organization

Step-by-step flow for end-users:

1. Users authenticate with their corporate credentials through your OIDC provider
2. The OIDC token is exchanged for temporary AWS credentials via Amazon Cognito
3. Claude Code uses these temporary credentials to access Amazon Bedrock
4. All access is logged and can be monitored through CloudWatch (if enabled)

## Architecture Overview

![Architecture Diagram](assets/images/credential-flow-diagram.png)

### Authentication Flow

1. **User initiates authentication**: User requests access to Amazon Bedrock through Claude Code
2. **OIDC authentication**: User authenticates with their OIDC provider and receives an ID token
3. **Token submission to Cognito**: Application sends the OIDC ID token to Amazon Cognito
4. **Cognito requests AWS credentials**: Cognito exchanges the token with AWS IAM
5. **IAM returns credentials**: AWS IAM validates and returns temporary AWS credentials
6. **Cognito returns credentials**: Cognito passes the temporary credentials back to the application
7. **Access Amazon Bedrock**: Application uses the temporary credentials to call Amazon Bedrock
8. **Bedrock response**: Amazon Bedrock processes the request and returns the response

### Cost

_You are responsible for the cost of the AWS services used while running this solution._

### Sample Cost Table

The following table provides a sample cost breakdown for deploying this solution with 5,000 monthly active users in the US East (N. Virginia) Region for one month (monitoring is separate).

| AWS service            | Dimensions                 | Cost [USD] |
| ---------------------- | -------------------------- | ---------- |
| **Total monthly cost** | 5,000 monthly active users | **$74.25** |

Based on AWS Pricing Calculator: [View Detailed Estimate](https://calculator.aws/#/estimate?id=df630701f37a3ab19cae0ebfa75eb33c86d7b31a)

## Prerequisites

### For Deployment (IT Administrators)

**Software Requirements:**

- Python 3.8-3.13
- Poetry (dependency management)
- AWS CLI v2
- Git

**AWS Requirements:**

- AWS account with appropriate IAM permissions to create:
  - CloudFormation stacks
  - Cognito Identity Pools
  - IAM roles and policies
  - (Optional) ECS tasks and CloudWatch dashboards
- Amazon Bedrock activated in target regions

**OIDC Provider Requirements:**

- Existing OIDC identity provider (Okta, Azure AD, Auth0, etc.)
- Ability to create OIDC applications
- Redirect URI support for `http://localhost:8400/callback`

### For End Users

**Software Requirements:**

- AWS CLI v2 or any AWS SDK
- Web browser for authentication
- macOS, Linux, or Windows operating system

**No AWS account required** - users authenticate through the organization's identity provider and receive temporary credentials.

### Supported AWS Regions

The solution can be deployed in any AWS region that supports:

- Amazon Cognito Identity Pools
- Amazon Bedrock
- (Optional) Amazon ECS Fargate for monitoring

Users can access Bedrock in any region you configure during setup, regardless of where the authentication infrastructure is deployed.

## Implementation

### Step 1: Initialize Configuration

Run the interactive setup wizard:

```bash
poetry run ccwb init
```

The wizard will guide you through:

- OIDC provider configuration (domain, client ID)
- AWS region selection for infrastructure
- Amazon Bedrock region access configuration
- Credential storage method (keyring or session files)
- Optional monitoring setup with VPC configuration

### Step 2: Deploy Infrastructure

Deploy the AWS CloudFormation stacks:

```bash
poetry run ccwb deploy
```

This creates the following AWS resources:

**Authentication Infrastructure:**

- Amazon Cognito Identity Pool for OIDC federation
- IAM OIDC Provider trust relationship
- IAM role with policies for:
  - Bedrock model invocation in specified regions
  - CloudWatch metrics (if monitoring enabled)

**Optional Monitoring Infrastructure:**

- VPC and networking resources (or integration with existing VPC)
- ECS Fargate cluster running OpenTelemetry collector
- Application Load Balancer for OTLP ingestion
- CloudWatch Log Groups and Metrics
- CloudWatch Dashboard with usage analytics
- Kinesis Data Firehose for streaming metrics to S3
- Amazon Athena for SQL analytics on collected metrics
- S3 bucket for long-term metrics storage

### Step 3: Create Distribution Package

Build the package for end users:

```bash
poetry run ccwb package
```

This creates a `dist/` folder containing:

- `credential-process-macos` - Authentication executable for macOS
- `credential-process-linux` - Authentication executable for Linux
- `config.json` - Embedded configuration
- `install.sh` - Installation script (auto-detects platform)
- `README.md` - User instructions
- `.claude/settings.json` - Claude Code telemetry settings (if monitoring enabled)
- `otel-helper-macos` - OTEL helper executable for macOS (if monitoring enabled)
- `otel-helper-linux` - OTEL helper executable for Linux (if monitoring enabled)

The package builder:

- Automatically builds binaries for both macOS and Linux by default
- Uses Docker for cross-platform Linux builds when running on macOS
- Includes the OTEL helper for extracting user attributes from JWT tokens
- Creates a unified installer that auto-detects the user's platform

### Step 4: Test the Setup

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

## End User Experience

### Installation

End users receive the `dist/` folder and run:

```bash
./install.sh
```

This installs:

- Authentication executable at `~/claude-code-with-bedrock/credential-process`
- Configuration at `~/claude-code-with-bedrock/config.json`
- AWS profile named `ClaudeCode` with credential process integration

### Using Claude Code

After installation, users can use Claude Code with Amazon Bedrock:

1. **Install Claude Code** (if not already installed):

   ```bash
   npm install -g @anthropic-ai/claude-code
   ```

2. **Configure environment for Bedrock**:

   ```bash
   # Set the AWS profile created by the installer
   export AWS_PROFILE=ClaudeCode
   ```

3. **Start Claude Code**:

   ```bash
   # Navigate to your project directory
   cd /path/to/your/project

   # Start Claude Code
   claude
   ```

Claude Code will automatically use your organization's authentication to access Amazon Bedrock.

### Authentication Process

1. On first use, a browser window opens for OIDC authentication
2. Users log in with their corporate credentials
3. Temporary AWS credentials are cached (based on configured storage method)
4. Subsequent calls use cached credentials until expiration
5. Automatic re-authentication when credentials expire

## Monitoring and Operations

### Available Metrics (when monitoring is enabled)

The optional CloudWatch dashboard provides:

- **Usage Metrics**: Requests per user, model, and region
- **Token Consumption**: Input/output tokens with cost estimation
- **Performance Metrics**: Response times and error rates
- **User Activity**: Active users and authentication patterns

## CLI Commands

The solution includes a comprehensive CLI tool (`ccwb`) for deployment and management:

- `ccwb init` - Interactive setup wizard for initial configuration
- `ccwb deploy` - Deploy AWS infrastructure (CloudFormation stacks)
- `ccwb package` - Build distribution package for end users
- `ccwb test` - Test authentication and Bedrock access
- `ccwb status` - Check deployment status and configuration
- `ccwb destroy` - Remove all deployed infrastructure
- `ccwb cleanup` - Clean up local configuration files

## Additional Resources

### Documentation

**Getting Started:**
- [CLI Reference](/assets/docs/CLI_REFERENCE.md) - Complete command reference for the `ccwb` tool

**Architecture & Deployment:**
- [Architecture Guide](/assets/docs/ARCHITECTURE.md) - System architecture and design decisions
- [Deployment Guide](/assets/docs/DEPLOYMENT.md) - Detailed deployment instructions and options
- [Local Testing Guide](/assets/docs/LOCAL_TESTING.md) - Testing the solution locally before deployment

**Monitoring & Analytics:**
- [Monitoring and Telemetry Guide](/assets/docs/MONITORING.md) - Guide to deploying and using Claude Code Telemetry with OpenTelemetry
- [Analytics Guide](/assets/docs/ANALYTICS.md) - Advanced analytics with Kinesis Firehose, S3 data lake, and Athena SQL queries

**OIDC Provider Setup Guides:**
- [Okta Setup](/assets/docs/providers/okta-setup.md)
- [Microsoft Entra ID (Azure AD) Setup](/assets/docs/providers/microsoft-entra-id-setup.md)
- [Auth0 Setup](/assets/docs/providers/auth0-setup.md)
- [Cognito User Pool Setup](/assets/docs/providers/cognito-user-pool-setup.md)

### Supported OIDC Providers

Detailed setup guides are available for:

- [Okta](/assets/docs/providers/okta-setup.md)
- [Microsoft Entra ID (Azure AD)](/assets/docs/providers/microsoft-entra-id-setup.md)
- [Auth0](/assets/docs/providers/auth0-setup.md)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
