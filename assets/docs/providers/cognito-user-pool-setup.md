# AWS Cognito User Pool Setup Guide

This guide explains how to set up an AWS Cognito User Pool for use with Claude Code authentication. The User Pool can be used standalone or integrated with external identity providers like Amazon Federate/Midway.

## Overview

The CloudFormation template creates a Cognito User Pool with:
- OAuth2 Authorization Code flow
- Proper token validity settings
- Support for external OIDC providers
- Pre-configured attribute mappings

## Prerequisites

- AWS CLI configured with appropriate credentials
- Permissions to create Cognito User Pools and IAM roles
- A unique domain prefix for your Cognito domain

## Quick Start

### 1. Deploy the User Pool

```bash
# Clone the repository
git clone <repository-url>
cd claude-code-auth-setup

# Deploy the User Pool stack
aws cloudformation deploy \
  --template-file deployment/infrastructure/cognito-user-pool-setup.yaml \
  --stack-name claude-code-user-pool \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    UserPoolName=claude-code-auth \
    DomainPrefix=my-unique-domain-prefix \
    CallbackURLs=http://localhost:8400/callback
```

### 2. Get the Configuration Values

```bash
# Get User Pool ID
aws cloudformation describe-stacks \
  --stack-name claude-code-user-pool \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text

# Get Client ID
aws cloudformation describe-stacks \
  --stack-name claude-code-user-pool \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
  --output text

# Get Domain
aws cloudformation describe-stacks \
  --stack-name claude-code-user-pool \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolDomain`].OutputValue' \
  --output text
```

### 3. Configure Claude Code

```bash
# Initialize Claude Code with your User Pool
poetry run ccwb init

# When prompted, enter:
# - Provider Domain: <your-domain-prefix>.auth.<region>.amazoncognito.com
# - User Pool ID: <from step 2>
# - Client ID: <from step 2>
```

### 4. Deploy the Identity Pool

```bash
# Deploy the authentication infrastructure
poetry run ccwb deploy --type auth
```

## Configuration Options

### Basic Parameters

- `UserPoolName`: Name for your User Pool (default: claude-code-auth)
- `DomainPrefix`: Unique prefix for Cognito domain (required)
- `CallbackURLs`: OAuth2 callback URLs (default: http://localhost:8400/callback)
- `LogoutURLs`: OAuth2 logout URLs (default: http://localhost:8400/logout)

### Amazon Federate/Midway Parameters (Optional)

For Amazon internal use with Federate/Midway:

- `FederateEnvironment`: 'none', 'integ', or 'prod' (default: none)
- `FederateClientId`: Client ID from Federate service profile
- `FederateClientSecret`: Client secret from Federate service profile

## User Pool Configuration

The template creates a User Pool with the following settings:

### Sign-in Options
- Username with email alias
- Email as required attribute
- preferred_username as required attribute

### Security Settings
- Self-registration disabled
- Password policy: 8+ chars, upper/lower/numbers/symbols
- MFA optional (can be configured per user)
- Token revocation enabled
- Prevent user existence errors enabled

### Token Validity
- Authentication flow session: 3 minutes
- Refresh token: 600 minutes (10 hours)
- Access token: 10 minutes
- ID token: 60 minutes

### OAuth2 Configuration
- Authorization code flow only
- Scopes: openid, email, profile
- No implicit grant flow

## Adding Users

Since self-registration is disabled, you need to create users manually:

### Via AWS Console
1. Navigate to Cognito > User pools > Your pool
2. Click "Create user"
3. Enter username and temporary password
4. User will need to change password on first login

### Via AWS CLI
```bash
aws cognito-idp admin-create-user \
  --user-pool-id <your-user-pool-id> \
  --username <username> \
  --user-attributes Name=email,Value=user@example.com \
  --temporary-password <temp-password>
```

## Integrating External Identity Providers

### Amazon Federate/Midway (Amazon Internal)

If you deployed with Federate parameters, the integration is automatic. Otherwise:

1. Create a Federate service profile at:
   - Testing: https://integ.ep.federate.a2z.com/
   - Production: https://prod.ep.federate.a2z.com/

2. Configure the service profile:
   - Protocol: OIDC
   - Redirect URI: `https://<domain-prefix>.auth.<region>.amazoncognito.com/oauth2/idpresponse`
   - Claims: EMAIL, GIVEN_NAME, FAMILY_NAME
   - Groups: Configure your LDAP/ANT/POSIX groups

3. In Cognito Console, add the identity provider:
   - Type: OpenID Connect
   - Provider name: midway
   - Client ID/Secret: From Federate
   - Issuer URL: https://idp.federate.amazon.com
   - Attribute mappings as shown in template outputs

### Other OIDC Providers

Similar process for Okta, Auth0, Azure AD:
1. Configure the provider with redirect URI
2. Add as OIDC identity provider in Cognito
3. Map attributes appropriately
4. Update app client supported identity providers

## Troubleshooting

### Domain Already Exists
If you get a domain conflict error, choose a different `DomainPrefix`. Cognito domains must be globally unique.

### Missing Outputs
Ensure the stack deployment completed successfully:
```bash
aws cloudformation describe-stacks \
  --stack-name claude-code-user-pool \
  --query 'Stacks[0].StackStatus'
```

### Authentication Issues
Check that:
1. User exists in the User Pool
2. Callback URL matches exactly
3. App client has correct identity providers

## Cleanup

To remove the User Pool:
```bash
aws cloudformation delete-stack --stack-name claude-code-user-pool
```

Note: This will delete all users and configurations. Back up any important data first.