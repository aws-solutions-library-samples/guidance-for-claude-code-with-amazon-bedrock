# E2E Integration Testing

## Overview

The E2E test harness validates the full deployment lifecycle:
`ccwb deploy` → validate stacks → invoke Bedrock → quota enforcement → `ccwb destroy`

It uses **Direct STS federation** (no Cognito, no IdP) via GitHub Actions OIDC.

---

## Infrastructure Requirements

### 1. Dedicated AWS Account

A standalone AWS account (or isolated OU) for E2E testing. This account will have CloudFormation stacks created and destroyed on every run.

**Why separate:** Tests create and destroy real infrastructure. An isolated account prevents accidental impact on production resources and simplifies budget controls.

### 2. GitHub OIDC Identity Provider

Create an IAM OIDC identity provider in the test account that trusts GitHub Actions:

```bash
aws iam create-open-id-connect-provider \
  --url "https://token.actions.githubusercontent.com" \
  --client-id-list "sts.amazonaws.com" \
  --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea1"
```

### 3. IAM Role for CI

Create a role that GitHub Actions can assume via OIDC:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock:*"
        }
      }
    }
  ]
}
```

**Permissions the role needs:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CloudFormationFullAccess",
      "Effect": "Allow",
      "Action": "cloudformation:*",
      "Resource": "arn:aws:cloudformation:*:ACCOUNT_ID:stack/ccwb-e2e-*/*"
    },
    {
      "Sid": "InfraResources",
      "Effect": "Allow",
      "Action": [
        "cognito-identity:*",
        "cognito-idp:*",
        "iam:*Role*",
        "iam:*Policy*",
        "iam:*InstanceProfile*",
        "lambda:*",
        "dynamodb:*",
        "s3:*",
        "ssm:*",
        "logs:*",
        "cloudwatch:*",
        "kms:*"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/ccwb-test": "true"
        }
      }
    },
    {
      "Sid": "BedrockInvoke",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock-runtime:InvokeModel",
        "bedrock-runtime:Converse"
      ],
      "Resource": "*"
    },
    {
      "Sid": "TaggingAndDescribe",
      "Effect": "Allow",
      "Action": [
        "tag:GetResources",
        "cloudformation:DescribeStacks",
        "cloudformation:ListStacks",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

**Note:** The actual permissions may need to be broader for initial setup (CloudFormation creates IAM roles, Cognito pools, etc.). Start with `AdministratorAccess` scoped to the test account, then narrow after first successful run.

### 4. GitHub Repository Secrets

Add these secrets to the repository (or a protected `e2e-test` environment):

| Secret | Value | Description |
|--------|-------|-------------|
| `E2E_AWS_ACCOUNT_ID` | `123456789012` | Test account ID |
| `E2E_ROLE_ARN` | `arn:aws:iam::123456789012:role/ccwb-e2e-ci` | IAM role ARN |
| `E2E_AWS_REGION` | `us-east-1` | Primary test region |

### 5. Budget Alarm

```bash
aws budgets create-budget \
  --account-id ACCOUNT_ID \
  --budget '{
    "BudgetName": "ccwb-e2e-monthly",
    "BudgetLimit": {"Amount": "50", "Unit": "USD"},
    "TimeUnit": "MONTHLY",
    "BudgetType": "COST"
  }' \
  --notifications-with-subscribers '[{
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 80
    },
    "Subscribers": [{
      "SubscriptionType": "EMAIL",
      "Address": "maintainer@example.com"
    }]
  }]'
```

### 6. Cleanup Safety Net

A scheduled Lambda (or EventBridge rule) that deletes any CloudFormation stack matching `ccwb-e2e-*` that's older than 2 hours. Prevents orphaned resources from failed test runs.

```python
# Lambda: cleanup_stale_e2e_stacks
import boto3
from datetime import datetime, timezone, timedelta

def handler(event, context):
    cf = boto3.client('cloudformation')
    stacks = cf.list_stacks(StackStatusFilter=['CREATE_COMPLETE', 'UPDATE_COMPLETE'])
    
    for stack in stacks['StackSummaries']:
        if stack['StackName'].startswith('ccwb-e2e-'):
            age = datetime.now(timezone.utc) - stack['CreationTime']
            if age > timedelta(hours=2):
                cf.delete_stack(StackName=stack['StackName'])
```

---

## Setup Checklist

- [ ] Create dedicated AWS account (or use existing sandbox)
- [ ] Create GitHub OIDC provider in account
- [ ] Create IAM role with trust policy + permissions above
- [ ] Add `E2E_ROLE_ARN` secret to repo (or `e2e-test` environment)
- [ ] Add `E2E_AWS_REGION` secret
- [ ] Set up budget alarm ($50/month)
- [ ] Deploy cleanup Lambda (optional but recommended)
- [ ] Enable Bedrock model access in the test region (Claude models need to be enabled in the console)
- [ ] Run workflow manually to verify: `gh workflow run e2e-deploy.yml`

---

## Cost Estimate

| Resource | Per Run | Nightly (30 runs/month) |
|----------|---------|------------------------|
| CloudFormation | $0 | $0 |
| Cognito Identity Pool | $0 (free tier) | $0 |
| DynamoDB (quota tables) | $0 (on-demand, minimal) | <$1 |
| Lambda (quota check) | $0 (free tier) | $0 |
| Bedrock (1-2 test invocations) | ~$0.01 | ~$0.30 |
| SSM Parameters | $0 | $0 |
| S3 (if deployed) | <$0.01 | <$0.30 |
| **Total** | **~$0.02** | **~$1-2/month** |

Well within free tier for most resources. Bedrock is the only meaningful cost.
