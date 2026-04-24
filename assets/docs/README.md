# User Documentation

This folder contains documentation for users implementing and operating Claude Code on AWS infrastructure, with focus on the Enterprise Authentication deployment pattern.

## Getting Started

### CLI Reference

- **File**: [CLI_REFERENCE.md](./CLI_REFERENCE.md)
- **Purpose**: Complete command reference for ccwb
- **Audience**: IT administrators deploying the solution

### Deployment Guide

- **File**: [DEPLOYMENT.md](./DEPLOYMENT.md)
- **Purpose**: Step-by-step deployment instructions
- **Audience**: IT administrators

### Architecture Overview

- **File**: [ARCHITECTURE.md](./ARCHITECTURE.md)
- **Purpose**: Technical architecture details
- **Audience**: Technical teams and architects

### Local Testing

- **File**: [LOCAL_TESTING.md](./LOCAL_TESTING.md)
- **Purpose**: Testing the solution before full deployment
- **Audience**: IT administrators

## Operations

### Monitoring Setup

- **File**: [MONITORING.md](./MONITORING.md)
- **Purpose**: CloudWatch monitoring configuration and OpenTelemetry setup
- **Audience**: IT administrators managing monitoring

### Analytics Pipeline

- **File**: [ANALYTICS.md](./ANALYTICS.md)
- **Purpose**: Setup and usage of the analytics pipeline for tracking Claude Code metrics
- **Audience**: IT administrators managing usage analytics

## Provider Configuration

### OIDC Provider Setup Guides

- **Folder**: [providers/](./providers/)
- **Okta**: [okta-setup.md](./providers/okta-setup.md)
- **Microsoft Entra ID (Azure AD)**: [microsoft-entra-id-setup.md](./providers/microsoft-entra-id-setup.md)
- **Auth0**: [auth0-setup.md](./providers/auth0-setup.md)
- **AWS Cognito User Pool**: [cognito-user-pool-setup.md](./providers/cognito-user-pool-setup.md)
