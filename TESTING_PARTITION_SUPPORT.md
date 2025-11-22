# Testing AWS Partition Support

This document outlines how to verify that the GovCloud partition support changes work correctly in both AWS Commercial and GovCloud regions.

## What Changed

All CloudFormation templates now use `${AWS::Partition}` instead of hardcoded `arn:aws:` values. This allows the same templates to work across:
- **AWS Commercial** (`aws` partition)
- **AWS GovCloud** (`aws-us-gov` partition)
- **AWS China** (`aws-cn` partition)

## Pre-Deployment Validation

### 1. CloudFormation Template Validation ✅

All templates have been validated successfully:

```bash
# Validate OTEL collector
aws cloudformation validate-template \
  --template-body file://deployment/infrastructure/otel-collector.yaml \
  --region us-east-1

# Validate Cognito Identity Pool
aws cloudformation validate-template \
  --template-body file://deployment/infrastructure/cognito-identity-pool.yaml \
  --region us-east-1

# Validate Analytics Pipeline
aws cloudformation validate-template \
  --template-body file://deployment/infrastructure/analytics-pipeline.yaml \
  --region us-east-1
```

**Result**: All templates validate successfully ✅

### 2. Verify Partition Resolution

The `${AWS::Partition}` pseudo-parameter automatically resolves to:
- `aws` in commercial regions (us-east-1, us-west-2, etc.)
- `aws-us-gov` in GovCloud regions (us-gov-west-1, us-gov-east-1)
- `aws-cn` in China regions (cn-north-1, cn-northwest-1)

## Testing in AWS Commercial (Available Now)

### Test 1: Deploy Auth Stack

```bash
poetry run ccwb deploy auth --profile default
```

**Expected**: Stack deploys successfully with ARNs like:
- `arn:aws:bedrock:us-east-1:*::foundation-model/*`
- `arn:aws:logs:us-east-1:ACCOUNT_ID:log-group:/aws/claude-code/metrics`

### Test 2: Deploy Monitoring Stack (if enabled)

```bash
poetry run ccwb deploy networking
poetry run ccwb deploy monitoring
```

**Expected**: 
- TaskRole policy correctly references `arn:aws:logs:...`
- SSM parameters use `arn:aws:ssm:...`

### Test 3: Deploy Analytics Stack (if enabled)

```bash
poetry run ccwb deploy analytics
```

**Expected**:
- Glue resources use `arn:aws:glue:...`
- All IAM policies work correctly

### Test 4: Verify Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name <your-stack-name> \
  --region us-east-1 \
  --query 'Stacks[0].Outputs'
```

**Expected**: All outputs show correct ARNs with `arn:aws:` prefix

## Testing in AWS GovCloud (When Available)

### Test 1: Deploy Auth Stack in GovCloud

```bash
# Configure for GovCloud
poetry run ccwb init
# Select us-gov-west-1 or us-gov-east-1
# Select GovCloud model (us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0)

poetry run ccwb deploy auth --profile default
```

**Expected**: Stack deploys successfully with ARNs like:
- `arn:aws-us-gov:bedrock:us-gov-west-1:*::foundation-model/*`
- `arn:aws-us-gov:logs:us-gov-west-1:ACCOUNT_ID:log-group:/aws/claude-code/metrics`

### Test 2: Deploy Monitoring Stack in GovCloud

```bash
poetry run ccwb deploy networking
poetry run ccwb deploy monitoring
```

**Expected**: 
- TaskRole policy correctly references `arn:aws-us-gov:logs:...`
- SSM parameters use `arn:aws-us-gov:ssm:...`
- No "Partition 'aws' is not valid" errors

### Test 3: Verify Stack Outputs in GovCloud

```bash
aws cloudformation describe-stacks \
  --stack-name <your-stack-name> \
  --region us-gov-west-1 \
  --query 'Stacks[0].Outputs'
```

**Expected**: All outputs show correct ARNs with `arn:aws-us-gov:` prefix

## Files Changed

### CloudFormation Templates
1. `deployment/infrastructure/otel-collector.yaml`
   - Fixed TaskRole CloudWatch Logs ARNs (2 occurrences)
   - Fixed SSM Parameter ARNs (2 occurrences)

2. `deployment/infrastructure/cognito-identity-pool.yaml`
   - Fixed CloudTrail ARNs (2 occurrences)

3. `deployment/infrastructure/analytics-pipeline.yaml`
   - Fixed Glue catalog, database, and table ARNs (3 occurrences)

4. `deployment/infrastructure/bedrock-auth-*.yaml` (all auth templates)
   - Already using `${AWS::Partition}` for Bedrock ARNs ✅

### Python Code
1. `source/claude_code_with_bedrock/cli/utils/cloudformation.py`
   - Fixed S3 URL construction to be partition-aware
   - Detects bucket region and uses correct endpoint

2. `source/claude_code_with_bedrock/models.py`
   - Added GovCloud model configurations
   - Added `us-gov` cross-region profile

### Configuration
1. `.gitignore`
   - Added `.venv/` to prevent virtual environments from being committed
   - Added `.kiro/settings/mcp.json` to protect tokens

## Backward Compatibility

✅ **All changes are backward compatible**

- Commercial region deployments continue to work exactly as before
- The `${AWS::Partition}` pseudo-parameter has been available since CloudFormation's inception
- No changes to API calls or user-facing functionality
- Existing stacks can be updated without issues

## Rollback Plan

If issues are discovered:

1. **Revert CloudFormation templates**:
   ```bash
   git revert <commit-hash>
   ```

2. **Update existing stacks**:
   ```bash
   poetry run ccwb deploy <stack-type>
   ```

3. **No data loss**: All changes are to IAM policies and ARN formats only

## Success Criteria

- ✅ All CloudFormation templates validate successfully
- ✅ Auth stack deploys in commercial region
- ✅ Monitoring stack deploys in commercial region (if enabled)
- ✅ Analytics stack deploys in commercial region (if enabled)
- ⏳ Auth stack deploys in GovCloud region (pending access)
- ⏳ Monitoring stack deploys in GovCloud region (pending access)
- ⏳ No "Partition 'aws' is not valid" errors in GovCloud

## Additional Verification

### Check IAM Policy Simulation

```bash
# Test that IAM policies work correctly
aws iam simulate-principal-policy \
  --policy-source-arn <role-arn> \
  --action-names logs:PutLogEvents \
  --resource-arns "arn:aws:logs:us-east-1:ACCOUNT_ID:log-group:/aws/claude-code/metrics:*"
```

### Check CloudFormation Change Sets

Before deploying to production, create change sets to preview changes:

```bash
aws cloudformation create-change-set \
  --stack-name <stack-name> \
  --template-body file://deployment/infrastructure/otel-collector.yaml \
  --change-set-name partition-support-update \
  --parameters <your-parameters>

aws cloudformation describe-change-set \
  --stack-name <stack-name> \
  --change-set-name partition-support-update
```

## Notes

- Managed policy ARNs (like `arn:aws:iam::aws:policy/...`) don't need partition variables - AWS handles these automatically
- The boto3 SDK automatically uses correct endpoints based on region, no code changes needed
- S3 URL construction now detects partition from bucket region
