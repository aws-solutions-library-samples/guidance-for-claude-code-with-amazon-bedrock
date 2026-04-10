# Product Overview

This project is **Guidance for Claude Code with Amazon Bedrock** — an enterprise deployment toolkit that enables organizations to run Claude Code (Anthropic's AI coding assistant) through Amazon Bedrock using federated identity.

## What It Does

- Integrates corporate OIDC identity providers (Okta, Azure AD, Auth0, Cognito User Pools) with AWS IAM to issue temporary Bedrock credentials
- Eliminates API key management — users authenticate with corporate SSO
- Provides a CLI tool (`ccwb`) for IT administrators to deploy, configure, and manage the infrastructure
- Builds platform-specific installer packages (Windows, macOS ARM/Intel/Universal, Linux x86_64/ARM64)
- Supports optional monitoring via OpenTelemetry, CloudWatch dashboards, and per-user token quota enforcement

## Target Users

- **IT Administrators**: Deploy and manage the infrastructure via the `ccwb` CLI
- **End Users (developers)**: Authenticate with corporate credentials to use Claude Code with Bedrock — they receive packaged installers

## Key Concepts

- **Profiles**: Multi-deployment management from a single machine (`~/.ccwb/profiles/`)
- **Direct IAM OIDC Federation**: Recommended auth pattern — IdP tokens exchanged for temporary AWS credentials
- **Cognito Identity Pool**: Alternative auth pattern for legacy IdP integrations
- **Cross-Region Inference**: Routes Bedrock requests across AWS regions for availability
- **Application Inference Profiles**: Per-user Bedrock inference profiles (one per user per model) providing server-side usage tracking via native CloudWatch metrics. Provisioned automatically on first login via a dedicated Lambda (`InferenceProfileProvisionerFunction`) — users never call Bedrock management APIs directly. Feature is opt-in (`inference_profiles_enabled = true`).
- **Distribution**: Three methods — manual zip, presigned S3 URLs, or authenticated landing page portal
- **ABAC User Isolation**: IAM conditions enforce that each user can only invoke their own inference profiles (`aws:ResourceTag/user.email` must match the caller's principal tag). Applied across all auth stacks (Auth0, Okta, Cognito).

## Monitoring

Dual-source monitoring architecture:
- **OpenTelemetry (OTEL)**: Client-side metrics collected via ADOT Collector on ECS Fargate, forwarded to CloudWatch EMF. Used for session-level metrics (active time, code edit decisions, etc.). The OTEL collector is now deprecated for token tracking — kept for backward compatibility only.
- **Bedrock CloudWatch Metrics (authoritative for tokens)**: Server-side token metrics (InputTokenCount, OutputTokenCount, CacheReadInputTokenCount, CacheWriteInputTokenCount) emitted natively by AWS per Application Inference Profile. A `BedrockMetricsBridge` Lambda bridges these into the OTEL log group every 5 minutes so all dashboard widgets and quota checks work from a single source. Cannot be bypassed by client misconfiguration.
- Dashboard reads from the `Bedrock` CloudWatch namespace, dimensioned by `user.email` tag on inference profiles.

## Quota & Accounting (Server-Side)

Quota enforcement has moved server-side using IAM tag conditions on inference profiles:
- Each inference profile carries a `status` tag (`enabled` / `disabled`)
- IAM policy requires `aws:ResourceTag/status = enabled` on every `InvokeModel` call — enforced by AWS at call time, not bypassable by clients
- A `QuotaEnforcer` Lambda runs every 5 minutes: reads usage from `UserQuotaMetrics` DynamoDB, compares against `QuotaPolicies`, and tags profiles `disabled` when limits are exceeded
- Supports per-user, per-group, and default policies with daily/monthly limits and alert/block enforcement modes
- Worst-case enforcement lag: ~17 minutes after quota exceeded; every subsequent Bedrock call returns `AccessDeniedException` immediately
- Client-side quota check (via quota API endpoint) still exists as a secondary layer but is no longer the primary enforcement mechanism

## Session Tags (Direct Federation)

For direct IAM OIDC federation (without Cognito Identity Pool), session tags must be embedded in the JWT under the `https://aws.amazon.com/tags` claim. This is required for ABAC conditions to work. Auth0 supports this natively via a post-login Action; Microsoft Entra does not support URL-namespaced JWT claims, so the Cognito Identity Pool path is recommended for Entra.

## Current Version

2.3.0 — stable, production-ready. Follows [Semantic Versioning](https://semver.org/).
