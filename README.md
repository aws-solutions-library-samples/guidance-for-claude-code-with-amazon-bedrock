# Guidance for Claude Code with Amazon Bedrock

This guidance provides enterprise deployment patterns for Claude Code with Amazon Bedrock using existing identity providers. Integrates with your IdP (Okta, Azure AD, Auth0, Cognito User Pools) for centralized access control, audit trails, and usage monitoring across your organization.

## Key Features

### For Organizations

- **Enterprise IdP Integration**: Leverage existing OIDC identity providers (Okta, Azure AD, Auth0, etc.)
- **Centralized Access Control**: Manage Claude Code access through your identity provider
- **No API Key Management**: Eliminate the need to distribute or rotate long-lived credentials
- **Usage Monitoring**: Optional CloudWatch dashboards for tracking usage and costs
- **Multi-Region Support**: Configure which AWS regions users can access Bedrock in
- **Multi-Platform Support**: Windows, macOS (ARM & Intel), and Linux distributions

### For End Users

- **Seamless Authentication**: Log in with corporate credentials
- **Automatic Credential Refresh**: No manual token management required
- **AWS CLI/SDK Integration**: Works with any AWS tool or SDK
- **Multi-Profile Support**: Manage multiple authentication profiles
- **Cross-Platform**: Works on Windows, macOS, and Linux

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Prerequisites](#prerequisites)
4. [What Gets Deployed](#what-gets-deployed)
5. [Monitoring and Operations](#monitoring-and-operations)
6. [Additional Resources](#additional-resources)

## Quick Start

This guidance integrates Claude Code with your existing OIDC identity provider (Okta, Azure AD, Auth0, or Cognito User Pools) to provide federated access to Amazon Bedrock.

### What You Need

**Existing Identity Provider:**
You must have an active OIDC provider with the ability to create application registrations. The guidance federates this IdP with AWS IAM to issue temporary credentials for Bedrock access.

**AWS Environment:**

- AWS account with IAM and CloudFormation permissions
- Amazon Bedrock activated in target regions
- Python 3.10+ development environment for deployment

### What Gets Deployed

The deployment creates:

- IAM OIDC Provider or Cognito Identity Pool for federation
- IAM roles with scoped Bedrock access policies
- Platform-specific installation packages (Windows, macOS, Linux)
- Optional: OpenTelemetry monitoring infrastructure

**Deployment time:** 2-3 hours for initial setup including IdP configuration.

See [QUICK_START.md](QUICK_START.md) for complete step-by-step deployment instructions.

## Architecture Overview

This guidance uses Direct IAM OIDC federation as the recommended authentication pattern. This provides temporary AWS credentials with complete user attribution for audit trails and usage monitoring.

**Alternative:** Cognito Identity Pool is also supported for legacy IdP integrations. See [Deployment Guide](assets/docs/DEPLOYMENT.md) for comparison.

### Authentication Flow (Direct IAM Federation)

![Architecture Diagram](assets/images/credential-flow-direct-diagram.png)

1. **User initiates authentication**: User requests access to Amazon Bedrock through Claude Code
2. **OIDC authentication**: User authenticates with their OIDC provider and receives an ID token
3. **Token submission to IAM**: Application sends the OIDC ID token to Amazon Cognito
4. **IAM returns credentials**: AWS IAM validates and returns temporary AWS credentials
5. **Access Amazon Bedrock**: Application uses the temporary credentials to call Amazon Bedrock
6. **Bedrock response**: Amazon Bedrock processes the request and returns the response

## Prerequisites

### For Deployment (IT Administrators)

**Software Requirements:**

- Python 3.10-3.13
- Poetry (dependency management)
- AWS CLI v2
- Git

**AWS Requirements:**

- AWS account with appropriate IAM permissions to create:
  - CloudFormation stacks
  - IAM OIDC Providers or Cognito Identity Pools
  - IAM roles and policies
  - (Optional) Amazon Elastic Container Service (Amazon ECS) tasks and Amazon CloudWatch dashboards
  - (Optional) Amazon Athena, AWS Glue, AWS Lambda, and Amazon Data Firehose resources
  - (Optional) AWS CodeBuild
- Amazon Bedrock activated in target regions

**OIDC Provider Requirements:**

- Existing OIDC identity provider (Okta, Azure AD, Auth0, etc.)
- Ability to create OIDC applications
- Redirect URI support for `http://localhost:8400/callback`

### For End Users

**Software Requirements:**

- AWS CLI v2 (for credential process integration)
- Claude Code installed
- Web browser for SSO authentication

**No AWS account required** - users authenticate through your organization's identity provider and receive temporary credentials automatically.

**No Python, Poetry, or Git required** - users receive pre-built installation packages from IT administrators.

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

### Platform Support

The authentication tools support all major platforms:

| Platform | Architecture          | Build Method                | Installation |
| -------- | --------------------- | --------------------------- | ------------ |
| Windows  | x64                   | AWS CodeBuild (Nuitka)      | install.bat  |
| macOS    | ARM64 (Apple Silicon) | Native (PyInstaller)        | install.sh   |
| macOS    | Intel (x86_64)        | Cross-compile (PyInstaller) | install.sh   |
| macOS    | Universal (both)      | Universal2 (PyInstaller)    | install.sh   |
| Linux    | x86_64                | Docker (PyInstaller)        | install.sh   |
| Linux    | ARM64                 | Docker (PyInstaller)        | install.sh   |

**Build System:**

The package builder automatically creates executables for all platforms using PyInstaller (macOS/Linux) and AWS CodeBuild with Nuitka (Windows). All builds create standalone executables - no Python installation required for end users.

See [QUICK_START.md](QUICK_START.md#platform-builds) for detailed build configuration.

## What Gets Deployed

### Authentication Infrastructure

The `ccwb deploy` command creates:

**IAM Resources:**

- IAM OIDC Provider (for Direct IAM federation) or Cognito Identity Pool (for legacy IdP)
- IAM role with trust relationship for federated access
- IAM policies scoped to:
  - Bedrock model invocation in configured regions
  - CloudWatch metric publishing (if monitoring enabled)

**User Distribution Packages:**

- Platform-specific executables (Windows, macOS ARM64/Intel, Linux x64/ARM64)
- Installation scripts that configure AWS CLI credential process
- Pre-configured settings (OIDC provider, model selection, monitoring endpoints)

### Distribution Options (Optional)

After building packages, you can share them with users in three ways:

| Method                | Best For               | Authentication                 |
| --------------------- | ---------------------- | ------------------------------ |
| **Manual Sharing**    | Any size team          | None                           |
| **Presigned S3 URLs** | Automated distribution | None                           |
| **Landing Page**      | Self-service portal    | IdP (Okta/Azure/Auth0/Cognito) |

**Manual Sharing:** Zip the `dist/` folder and share via email or internal file sharing. No additional infrastructure required.

**Presigned URLs:** Generate time-limited S3 URLs for direct downloads. Automated but requires S3 bucket setup.

**Landing Page:** Self-service portal with IdP authentication, platform detection, and custom domain support. Full automation with compliance features.

See [Distribution Comparison](assets/docs/distribution/comparison.md) for detailed setup guides.

### Monitoring Infrastructure (Optional)

Enable usage visibility with OpenTelemetry monitoring stack:

**Components:**

- VPC and networking resources (or use existing VPC)
- ECS Fargate cluster running OpenTelemetry collector
- Application Load Balancer for metric ingestion
- CloudWatch dashboards with real-time usage metrics
- DynamoDB for metrics aggregation

**Optional Analytics Add-On:**

- Kinesis Data Firehose streaming metrics to S3
- S3 data lake for long-term storage
- Amazon Athena for SQL queries on historical data
- AWS Glue Data Catalog for schema management

See [QUICK_START.md](QUICK_START.md) for step-by-step deployment instructions.

## Monitoring and Operations

Optional OpenTelemetry monitoring provides comprehensive usage visibility for cost attribution, capacity planning, and productivity insights.

### Available Metrics

**Token Economics:**

- Input/output/cache token consumption by user, model, and type
- Prompt caching effectiveness (hit rates, token savings)
- Cost attribution by user, team, or department

**Code Activity:**

- Lines of code written vs accepted (productivity signal)
- File operations breakdown (edits, searches, reads)
- Programming language distribution

**Operational Health:**

- Active users and top consumers
- Usage patterns (hourly/daily heatmaps)
- Authentication and API error rates

### Infrastructure

The monitoring stack (deployed with `ccwb deploy monitoring`) includes:

- ECS Fargate running OpenTelemetry collector
- Application Load Balancer for metric ingestion
- CloudWatch dashboards for real-time visualization
- Optional: S3 data lake + Athena for historical analysis

See [Monitoring Guide](assets/docs/MONITORING.md) for setup details and dashboard examples.
See [Analytics Guide](assets/docs/ANALYTICS.md) for SQL queries on historical data.

## Additional Resources

### Getting Started

- [Quick Start Guide](QUICK_START.md) - Step-by-step deployment walkthrough
- [CLI Reference](assets/docs/CLI_REFERENCE.md) - Complete command reference for the `ccwb` tool

### Architecture & Deployment

- [Architecture Guide](assets/docs/ARCHITECTURE.md) - System architecture and design decisions
- [Deployment Guide](assets/docs/DEPLOYMENT.md) - Advanced deployment options
- [Distribution Comparison](assets/docs/distribution/comparison.md) - Presigned URLs vs Landing Page
- [Local Testing Guide](assets/docs/LOCAL_TESTING.md) - Testing before deployment

### Monitoring & Analytics

- [Monitoring Guide](assets/docs/MONITORING.md) - OpenTelemetry setup and dashboards
- [Analytics Guide](assets/docs/ANALYTICS.md) - S3 data lake and Athena SQL queries

### Identity Provider Setup

- [Okta](assets/docs/providers/okta-setup.md)
- [Microsoft Entra ID (Azure AD)](assets/docs/providers/microsoft-entra-id-setup.md)
- [Auth0](assets/docs/providers/auth0-setup.md)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
