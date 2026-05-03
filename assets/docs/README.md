# User Documentation

This folder contains documentation for users implementing and operating Claude Code on AWS infrastructure, with focus on the Enterprise Authentication deployment pattern.

## Deployment — Required Reading Order

Deployment has two sides: your **identity provider (IdP)** and **AWS infrastructure**. The IdP side must be completed first — the AWS wizard asks for values you get from your IdP.

### Step 1 — Configure your Identity Provider (do this first)

Choose your IdP and follow the setup guide before running `ccwb init`:

| Identity Provider | Guide |
|---|---|
| **Okta** | [okta-setup.md](./providers/okta-setup.md) |
| **Microsoft Entra ID (Azure AD)** | [microsoft-entra-id-setup.md](./providers/microsoft-entra-id-setup.md) |
| **Auth0** | [auth0-setup.md](./providers/auth0-setup.md) |
| **AWS Cognito User Pool** | [cognito-user-pool-setup.md](./providers/cognito-user-pool-setup.md) |
| **AWS IAM Identity Center (SSO)** | [iam-identity-center-setup.md](./providers/iam-identity-center-setup.md) |

### Step 2 — Deploy AWS infrastructure

Once you have your IdP **provider domain** and **client ID**, follow one of these:

- **[QUICK_START.md](../../QUICK_START.md)** — Primary step-by-step reference (recommended starting point)
- **[DEPLOYMENT.md](./DEPLOYMENT.md)** — More conceptual/narrative walkthrough of the same steps

### Reference

- **[CLI_REFERENCE.md](./CLI_REFERENCE.md)** — Complete `ccwb` command reference
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — Technical architecture details
- **[LOCAL_TESTING.md](./LOCAL_TESTING.md)** — Testing before full deployment

## Operations

### Monitoring Setup

- **File**: [MONITORING.md](./MONITORING.md)
- **Purpose**: CloudWatch monitoring configuration and OpenTelemetry setup
- **Audience**: IT administrators managing monitoring

### Analytics Pipeline

- **File**: [ANALYTICS.md](./ANALYTICS.md)
- **Purpose**: Setup and usage of the analytics pipeline for tracking Claude Code metrics
- **Audience**: IT administrators managing usage analytics

### Quota Management

- **File**: [QUOTA_MONITORING.md](./QUOTA_MONITORING.md)
- **Purpose**: Per-user and per-group token quota enforcement and alerts
- **Audience**: IT administrators managing usage costs

### Cost Attribution

- **File**: [COST_ATTRIBUTION.md](./COST_ATTRIBUTION.md)
- **Purpose**: Per-user and per-team cost tracking via CUR 2.0 and Cost Explorer
- **Audience**: IT administrators and finance teams

## Claude Cowork (Desktop)

### CoWork 3P Guide

- **File**: [COWORK_3P.md](./COWORK_3P.md)
- **Purpose**: Using this solution's credential helper with Claude Desktop in third-party platform mode
- **Audience**: IT administrators deploying Claude Cowork with Amazon Bedrock
