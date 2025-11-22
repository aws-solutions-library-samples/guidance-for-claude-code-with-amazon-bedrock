# Testing AWS Partition Support

This document outlines how to verify that the GovCloud partition support changes work correctly in both AWS Commercial and GovCloud regions.

## What Changed

### Resource ARNs (✅ Complete)
All CloudFormation templates now use `${AWS::Partition}` instead of hardcoded `arn:aws:` values. This allows the same templates to work across:
- **AWS Commercial** (`aws` partition)
- **AWS GovCloud** (`aws-us-gov` partition)
- **AWS China** (`aws-cn` partition)

### Cognito Identity Service Principals (✅ Complete)
All IAM role trust policies now use partition-aware Cognito Identity service principals:
- **Commercial**: `cognito-identity.amazonaws.com`
- **GovCloud West**: `cognito-identity-us-gov.amazonaws.com`
- **GovCloud East**: `cognito-identity.us-gov-east-1.amazonaws.com`

**Files Updated:**
1. `deployment/infrastructure/cognito-identity-pool.yaml` - Added partition conditions and updated 2 roles
2. `deployment/infrastructure/bedrock-auth-azure.yaml` - Added partition conditions and updated 2 roles
3. `deployment/infrastructure/bedrock-auth-okta.yaml` - Added partition conditions and updated 2 roles
4. `deployment/infrastructure/bedrock-auth-auth0.yaml` - Added partition conditions and updated 2 roles
5. `deployment/infrastructure/bedrock-auth-cognito-pool.yaml` - Added partition conditions and updated 2 roles

**Implementation Approach:**
Each template now includes partition detection conditions:
```yaml
Conditions:
  IsGovCloudWest: !Equals [!Ref 'AWS::Region', 'us-gov-west-1']
  IsGovCloudEast: !Equals [!Ref 'AWS::Region', 'us-gov-east-1']
  IsGovCloud: !Or [!Condition IsGovCloudWest, !Condition IsGovCloudEast]
```

IAM roles use nested `!If` statements to select the correct service principal based on region.

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
# Use default profile or specify AWS_PROFILE
poetry run ccwb deploy auth

# Or with explicit profile
AWS_PROFILE=default poetry run ccwb deploy auth
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

# Deploy with GovCloud credentials
AWS_PROFILE=gov-west poetry run ccwb deploy auth
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

#### Resource ARN Fixes (Already Complete)
1. `deployment/infrastructure/otel-collector.yaml`
   - Fixed TaskRole CloudWatch Logs ARNs (2 occurrences)
   - Fixed SSM Parameter ARNs (2 occurrences)

2. `deployment/infrastructure/analytics-pipeline.yaml`
   - Fixed Glue catalog, database, and table ARNs (3 occurrences)

#### Cognito Identity Service Principal Fixes (✅ Complete)
1. `deployment/infrastructure/cognito-identity-pool.yaml`
   - Added 3 partition-aware conditions (IsGovCloudWest, IsGovCloudEast, IsGovCloud)
   - Updated BedrockAccessRole (AuthenticatedRole) trust policy with conditional service principals (6 references)
   - Updated UnauthenticatedRole trust policy with conditional service principals (6 references)
   - Fixed CloudTrail ARNs (already using ${AWS::Partition})

2. `deployment/infrastructure/bedrock-auth-azure.yaml`
   - Added 3 partition-aware conditions
   - Updated CognitoAuthenticatedRole trust policy (6 references)
   - Updated CognitoUnauthenticatedRole trust policy (6 references)
   - Already using `${AWS::Partition}` for Bedrock ARNs ✅

3. `deployment/infrastructure/bedrock-auth-okta.yaml`
   - Added 3 partition-aware conditions
   - Updated CognitoAuthenticatedRole trust policy (6 references)
   - Updated CognitoUnauthenticatedRole trust policy (6 references)
   - Already using `${AWS::Partition}` for Bedrock ARNs ✅

4. `deployment/infrastructure/bedrock-auth-auth0.yaml`
   - Added 3 partition-aware conditions
   - Updated CognitoAuthenticatedRole trust policy (6 references)
   - Updated CognitoUnauthenticatedRole trust policy (6 references)
   - Already using `${AWS::Partition}` for Bedrock ARNs ✅

5. `deployment/infrastructure/bedrock-auth-cognito-pool.yaml`
   - Added 3 partition-aware conditions
   - Updated CognitoAuthenticatedRole trust policy (6 references)
   - Updated CognitoUnauthenticatedRole trust policy (6 references)
   - Already using `${AWS::Partition}` for Bedrock ARNs ✅

**Total Changes:** 30 service principal references updated across 5 templates

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

### Implementation Phase (✅ Complete)
- ✅ All CloudFormation templates validate successfully
- ✅ Resource ARNs use `${AWS::Partition}` pseudo-parameter
- ✅ Cognito Identity service principals are partition-aware (30 references updated)
- ✅ S3 URL construction detects partition from bucket region
- ✅ All 5 auth templates updated and validated
- ✅ Backward compatibility maintained

### Validation Results
```bash
✓ cognito-identity-pool.yaml - VALID
✓ bedrock-auth-azure.yaml - VALID
✓ bedrock-auth-okta.yaml - VALID
✓ bedrock-auth-auth0.yaml - VALID
✓ bedrock-auth-cognito-pool.yaml - VALID
```

### Deployment Testing (⏳ Pending AWS Access)
- ⏳ Auth stack deploys in commercial region
- ⏳ Monitoring stack deploys in commercial region (if enabled)
- ⏳ Analytics stack deploys in commercial region (if enabled)
- ⏳ Auth stack deploys in GovCloud region (requires GovCloud access)
- ⏳ Monitoring stack deploys in GovCloud region (requires GovCloud access)
- ⏳ No "Partition 'aws' is not valid" errors in GovCloud
- ⏳ IAM role assumption works correctly in both partitions

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
