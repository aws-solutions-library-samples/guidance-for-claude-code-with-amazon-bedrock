# Technical Architecture

This document provides technical details about the Claude Code authentication system architecture, design decisions, and integration patterns.

> **Note**: For deployment instructions, prerequisites, and operational guides, see the [main README](../../README.md).

## System Overview

The Claude Code authentication system enables secure, scalable access to Amazon Bedrock by federating enterprise identity providers through AWS Cognito. The architecture follows zero-trust principles with complete audit trails.

## Component Architecture

### Authentication Components

The core authentication component is the credential process located in `source/cognito_auth/`. This implements a complete OAuth2/OIDC client with PKCE flow for secure authentication without client secrets. When packaged for distribution, PyInstaller compiles this into a standalone executable that end users can run without needing Python installed. The credential process supports multiple identity providers including Okta, Azure AD, Auth0, and Cognito User Pools through a flexible provider registry system. Once authenticated, credentials are cached either in the operating system's secure keyring or in session files, depending on the organization's preference. The implementation follows the AWS CLI credential process protocol, making it transparent to any AWS SDK or tool.

The management CLI in `source/claude_code_with_bedrock/` provides IT administrators with tools to deploy and manage the infrastructure. Built on the Cleo framework, it offers an intuitive command-line interface for initialization, deployment, and package generation. This component is used only during setup and is not distributed to end users.

### AWS Infrastructure Components

The authentication infrastructure centers on an Amazon Cognito Identity Pool that federates OIDC tokens into AWS credentials. This creates a trust relationship between the organization's identity provider and AWS through an IAM OIDC Provider. The associated IAM role grants permissions specifically for Amazon Bedrock model invocation in configured regions. Every API call includes session tags containing the user's email and subject claim, ensuring complete attribution in CloudTrail logs.

#### IAM Permissions

The IAM role assigned to authenticated users grants the following Amazon Bedrock permissions:

- `bedrock:InvokeModel` - Invoke foundation models for text generation
- `bedrock:InvokeModelWithResponseStream` - Invoke models with streaming responses
- `bedrock:ListFoundationModels` - List available foundation models
- `bedrock:GetFoundationModel` - Get details about specific models
- `bedrock:GetFoundationModelAvailability` - Check model availability in regions
- `bedrock:ListInferenceProfiles` - List available cross-region inference profiles
- `bedrock:GetInferenceProfile` - Get details about specific inference profiles

These permissions are scoped to the configured regions and enable users to discover and invoke models through cross-region inference profiles, ensuring optimal performance and availability.

When monitoring is enabled, the solution deploys additional infrastructure to collect and analyze usage metrics. A VPC with public subnets hosts an ECS Fargate cluster running the OpenTelemetry collector. An Application Load Balancer provides the ingestion endpoint for metrics from Claude Code clients. The collector processes these metrics and forwards them to CloudWatch Logs in Embedded Metric Format, enabling real-time dashboards and alerting.

For organizations requiring detailed analytics, the optional analytics stack provides comprehensive usage analysis capabilities. Kinesis Data Firehose continuously streams metrics from CloudWatch Logs to an S3 data lake, with a Lambda function transforming the data into Parquet format for efficient querying. Amazon Athena enables SQL analytics on this data, with pre-configured partition projection eliminating the need for Glue crawlers. This architecture supports queries spanning months of historical data while keeping costs minimal through columnar storage and lifecycle policies.

## Authentication Flow

The authentication flow begins when Claude Code requests AWS credentials through the AWS CLI. The CLI invokes our credential process executable, which initiates an OAuth2 flow with PKCE (Proof Key for Code Exchange) to ensure security without requiring client secrets. A browser window opens automatically, directing the user to their organization's identity provider for authentication.

After successful authentication, the identity provider redirects back to the local callback server with an authorization code. The credential process exchanges this code for OIDC tokens, then presents the ID token to Amazon Cognito Identity Pool. Cognito validates the token and calls STS AssumeRoleWithWebIdentity to obtain temporary AWS credentials. These credentials include session tags containing the user's email and subject claim, ensuring every subsequent API call to Amazon Bedrock can be attributed to the specific user.

The temporary credentials are returned to Claude Code through the standard AWS CLI credential process protocol. By default, credentials last for one hour but can be configured up to eight hours. The entire flow operates without any client secrets or long-lived credentials, following zero-trust security principles. Credentials are cached securely using either the operating system's keyring service or encrypted session files, preventing repeated authentication requests during the session lifetime.

## AWS CLI Credential Process Protocol

The solution leverages the [AWS CLI external credential process](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sourcing-external.html), a feature that allows custom credential providers to integrate with AWS CLI. When the AWS CLI needs credentials for a profile configured with `credential_process`, it executes the specified program and expects JSON-formatted temporary credentials on stdout.

Our implementation returns credentials in the exact format required by the AWS CLI:

```json
{
  "Version": 1,
  "AccessKeyId": "ASIA...",
  "SecretAccessKey": "...",
  "SessionToken": "...",
  "Expiration": "2025-01-01T12:00:00Z"
}
```

## Package Distribution Architecture

The packaging and distribution system bridges the gap between IT administrators who deploy infrastructure and end users who need simple, foolproof installation. The `ccwb package` command creates a self-contained distribution that includes everything users need without requiring technical expertise.

During packaging, PyInstaller compiles the Python credential process into platform-specific executables. For macOS, it creates a universal binary supporting both Intel and Apple Silicon. For Linux, it uses Docker to ensure compatibility across distributions. These executables are completely standalone - users don't need Python, pip, or any other dependencies installed.

The package embeds the configuration created during deployment, including the Cognito Identity Pool ID retrieved from CloudFormation outputs. This eliminates any manual configuration for end users. The installer script detects the user's platform, copies the appropriate binary, creates the AWS CLI profile configuration, and sets up the credential process integration.

For organizations with monitoring enabled, the package also includes the OTEL helper executable and Claude Code settings. This provides a complete solution from authentication through telemetry without requiring users to understand the underlying complexity.

## Configuration Architecture

### Configuration Hierarchy

1. **Administrator Configuration** (`.ccwb-config/config.json`)

   - Created by `ccwb init` in the project directory
   - Contains deployment parameters and provider settings
   - Not distributed to end users

2. **End User Configuration** (`~/claude-code-with-bedrock/config.json`)

   - Embedded during package build
   - Contains runtime authentication parameters
   - Includes identity pool ID from deployed infrastructure

3. **Claude Code Settings** (`~/.claude/settings.json`)
   - Generated during package build
   - Contains OTEL endpoint and environment variables
   - Includes path to OTEL helper executable

## Security Architecture

The security architecture addresses several threat vectors inherent in enterprise authentication systems. Each design decision directly mitigates specific risks while maintaining usability.

Credential theft represents the most common attack vector in authentication systems. Traditional long-lived API keys create persistent risk - once stolen, they remain valid until manually revoked. Our architecture eliminates this risk by using only temporary credentials that expire automatically. These credentials typically last one hour, with a maximum configurable lifetime of eight hours. Even if credentials are somehow compromised, the attacker's window of opportunity is limited and closes automatically.

The OAuth2 authorization flow itself presents opportunities for interception attacks. An attacker who intercepts an authorization code could potentially exchange it for tokens. We implement PKCE (Proof Key for Code Exchange, RFC 7636) which generates a dynamic code verifier for each authentication request. This makes intercepted codes useless without the corresponding verifier. Additionally, a cryptographically random state parameter prevents cross-site request forgery attacks.

Token storage on end-user machines requires careful consideration. We provide two storage options: integration with the operating system's keyring service, which provides encrypted storage with OS-level access controls, or session files with restricted filesystem permissions. Both approaches prevent other users or processes from accessing stored credentials. The system automatically cleans up expired credentials to minimize the attack surface.

Privilege escalation attempts are contained through IAM policy design. The federated role grants only the minimum permissions required to invoke Bedrock models in specified regions. Session tags embedded in every credential set ensure that users cannot access resources beyond their authorization. These tags flow through to CloudTrail, creating an immutable audit trail.

Every API call to Amazon Bedrock includes the user's subject identifier. This means that CloudTrail captures these tags with every request, providing complete attribution. Authentication events through Cognito are similarly logged, creating a comprehensive security audit trail from login through API usage.
