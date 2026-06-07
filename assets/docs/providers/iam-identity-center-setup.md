# AWS IAM Identity Center Setup Guide

This guide covers setting up Claude Code with Bedrock using AWS IAM Identity Center (formerly AWS SSO) as the authentication method.

## When to Choose IAM Identity Center vs OIDC

### Choose IAM Identity Center (IDC) when:
- Your organization already uses AWS SSO/Identity Center for AWS access management
- You want to leverage existing AWS permission sets and user groups
- You need native AWS authentication without external identity providers
- You want simplified setup for AWS-first environments

### Choose OIDC when:
- You need per-user quota enforcement and monitoring
- You want detailed user attribution in metrics and logs
- Your organization uses external identity providers (Okta, Azure AD, etc.)
- You need fine-grained user access controls and JWT-based authorization

## What's NOT Supported with IAM Identity Center

⚠️ **Important Limitations:**

1. **No Quota Monitoring**: Per-user token quota enforcement is disabled as it requires JWT tokens from OIDC providers
2. **Per-User Attribution via STS**: OTEL metrics include user email extracted from the IAM assumed-role session name. This requires IAM Identity Center to use email as the session name (the default). Dashboard per-user widgets work automatically.
3. **No JWT Authorization**: The quota monitoring API Gateway cannot validate requests without an OIDC issuer

## Prerequisites

Before starting, ensure you have:

- AWS IAM Identity Center enabled in your AWS account
- A permission set created with appropriate Bedrock access (recommended: `BedrockDeveloperAccess`)
- Users assigned to the permission set
- AWS CLI v2 installed and configured

## Step-by-Step Deployment

### 1. Initialize Configuration

Run the Claude Code setup wizard and select IAM Identity Center:

```bash
poetry run ccwb init
```

When prompted for authentication method, choose:
```
❯ AWS IAM Identity Center (SSO)
```

### 2. Provide Identity Center Details

You'll be prompted for:

- **Start URL**: Your Identity Center portal URL (e.g., `https://company.awsapps.com/start`)
- **SSO Region**: The AWS region where Identity Center is configured
- **Account ID**: Your 12-digit AWS account number
- **Permission Set**: The name of your permission set (default: `BedrockDeveloperAccess`)

### 3. AWS Configuration

The wizard will generate an AWS config block and offer to append it to `~/.aws/config`:

```ini
[profile ClaudeCode]
sso_session = ClaudeCode-MyPool
sso_account_id = 123456789012
sso_role_name = BedrockDeveloperAccess
region = us-east-1

[sso-session ClaudeCode-MyPool]
sso_start_url = https://company.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access
```

### 4. Authenticate with AWS SSO

Before deploying, authenticate using the AWS CLI:

```bash
aws sso login --profile ClaudeCode
```

Verify your identity:

```bash
aws sts get-caller-identity --profile ClaudeCode
```

### 5. Deploy Infrastructure

Deploy the Claude Code infrastructure:

```bash
poetry run ccwb deploy
```

This will:
- Skip the quota monitoring stack (not compatible with IDC)
- Deploy the IAM role and Bedrock access policy
- Deploy monitoring and dashboard stacks (if enabled)

## Extending SSO Session Duration

By default, AWS SSO sessions expire after 8-12 hours. To extend this:

1. **In AWS Console**: Go to IAM Identity Center → Settings → Session settings
2. **Update Session Duration**: Set to maximum allowed (up to 7 days for programmatic access)
3. **Apply to Permission Sets**: Ensure your permission set inherits these settings

Example session settings:
- **Programmatic access**: 7 days
- **AWS Management Console access**: 12 hours

## Per-User Cost Attribution

IDC users get per-user OTEL attribution automatically. The credential-process
extracts the user email from the STS assumed-role ARN session name and writes
it to the OTEL cache. Dashboard widgets (Token Usage by User, Active Users)
work without additional configuration.

**Requirement:** IAM Identity Center must use email as the session name (this
is the default). The ARN format must be:
`arn:aws:sts::ACCOUNT:assumed-role/RoleName/user@company.com`

For additional cost tracking via CloudTrail:

### 1. Enable CloudTrail

```yaml
# Add to your monitoring configuration
CloudTrailEnabled: true
CloudTrailS3Bucket: my-company-cloudtrail-bucket
```

### 2. Query CloudTrail Logs

Use Athena or CloudWatch Logs Insights to query Bedrock API calls:

```sql
-- Athena query for user-specific Bedrock usage
SELECT 
    useridentity.sessioncontext.sessionissuer.principalid as user_id,
    eventname,
    COUNT(*) as api_calls,
    DATE_TRUNC('day', eventtime) as date
FROM cloudtrail_logs
WHERE 
    eventsource = 'bedrock.amazonaws.com'
    AND eventname LIKE 'InvokeModel%'
    AND eventtime >= current_timestamp - interval '30' day
GROUP BY 1,2,4
ORDER BY date DESC, api_calls DESC;
```

### 3. Create Custom Dashboards

Use the user identity from CloudTrail to create cost allocation reports and usage dashboards.

## Troubleshooting

### Common Issues

1. **"Profile not found" errors**
   ```bash
   # Verify your profile exists
   aws configure list-profiles
   
   # Test SSO authentication
   aws sso login --profile ClaudeCode
   ```

2. **"Access denied" for Bedrock**
   - Verify your permission set includes Bedrock permissions
   - Check that the deployed IAM role has the correct policies attached
   - Ensure you're using the correct AWS region for Bedrock access

3. **CloudFormation deployment failures**
   ```bash
   # Check stack status
   aws cloudformation describe-stacks --stack-name YourStackName
   
   # View stack events for errors
   aws cloudformation describe-stack-events --stack-name YourStackName
   ```

4. **SSO session expired**
   ```bash
   # Re-authenticate
   aws sso login --profile ClaudeCode
   
   # Verify credentials are refreshed
   aws sts get-caller-identity --profile ClaudeCode
   ```

### IAM Role Trust Policy Issues

If you encounter trust policy errors, verify the CloudFormation template deployed correctly:

```bash
# Check the federated role
aws iam get-role --role-name BedrockIDCFederatedRole

# Verify trust policy allows SSO principals
aws iam get-role --role-name BedrockIDCFederatedRole --query 'Role.AssumeRolePolicyDocument'
```

### Permission Set Configuration

Ensure your Identity Center permission set includes:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel*",
                "bedrock:GetFoundationModel",
                "bedrock:ListFoundationModels"
            ],
            "Resource": "*"
        }
    ]
}
```

## Migration from OIDC to IDC

To switch an existing OIDC profile to IDC:

1. **Backup current configuration**:
   ```bash
   cp ~/.ccwb/profiles/myprofile.json ~/.ccwb/profiles/myprofile-backup.json
   ```

2. **Re-run init with IDC**:
   ```bash
   poetry run ccwb init --profile myprofile
   ```
   Select "AWS IAM Identity Center (SSO)" when prompted.

3. **Redeploy infrastructure**:
   ```bash
   poetry run ccwb deploy
   ```
   The auth stack will be updated to use the IDC template instead of OIDC.

## Next Steps

After successful deployment:

- **Test Authentication**: Create and run a simple Claude Code script
- **Monitor Usage**: Use CloudWatch dashboards for system monitoring
- **Set Up Alerts**: Configure SNS notifications for system health
- **Train Users**: Share SSO login instructions with your team

For quota monitoring and per-user controls, consider using the OIDC authentication method instead.