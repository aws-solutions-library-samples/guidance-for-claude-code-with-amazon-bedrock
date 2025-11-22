# AWS Partition Support Assessment Report

**Date:** 2025-11-22
**Branch:** feat/govcloud-partition-support
**Objective:** Assess multi-partition support for AWS GovCloud and Commercial regions

---

## Executive Summary

The repository has made significant progress toward multi-partition support, but **critical issues remain** that will prevent deployment in AWS GovCloud regions. The main issue is hardcoded Cognito Identity service principals that are incompatible with GovCloud.

### Status: ⚠️ **INCOMPLETE - CRITICAL ISSUES FOUND**

---

## 1. Critical Issues That Will Block GovCloud Deployment

### Issue #1: Hardcoded Cognito Identity Service Principal ❌ CRITICAL

**Problem:**
All CloudFormation templates use `cognito-identity.amazonaws.com` as the service principal for IAM role trust policies. However, AWS GovCloud uses **different service principals**:

- **Commercial:** `cognito-identity.amazonaws.com`
- **GovCloud (US-West):** `cognito-identity-us-gov.amazonaws.com`
- **GovCloud (US-East):** `cognito-identity.us-gov-east-1.amazonaws.com`

**Impact:**
IAM roles will fail to be assumed by Cognito Identity Pools in GovCloud, causing authentication failures.

**Reference:**
[Amazon Cognito in AWS GovCloud (US)](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-cog.html)

**Affected Files (30 occurrences across 6 files):**

1. `deployment/infrastructure/cognito-identity-pool.yaml`
   - Lines 180, 186, 188, 202, 206, 208

2. `deployment/infrastructure/bedrock-auth-azure.yaml`
   - Lines 203, 208, 210, 229, 234, 236

3. `deployment/infrastructure/bedrock-auth-okta.yaml`
   - Lines 202, 207, 209, 228, 233, 235

4. `deployment/infrastructure/bedrock-auth-auth0.yaml`
   - Lines 211, 216, 218, 237, 242, 244

5. `deployment/infrastructure/bedrock-auth-cognito-pool.yaml`
   - Lines 211, 217, 219, 238, 243, 245

**Example from cognito-identity-pool.yaml:180:**
```yaml
Principal:
  Federated: cognito-identity.amazonaws.com  # ❌ Hardcoded
Action:
  - 'sts:AssumeRoleWithWebIdentity'
Condition:
  StringEquals:
    'cognito-identity.amazonaws.com:aud': !Ref BedrockIdentityPool  # ❌ Hardcoded
  'ForAnyValue:StringLike':
    'cognito-identity.amazonaws.com:amr': authenticated  # ❌ Hardcoded
```

---

## 2. What Was Already Fixed ✅

The following changes were successfully implemented:

### ✅ Resource ARNs (Using `${AWS::Partition}`)

**Fixed in:**
- `deployment/infrastructure/otel-collector.yaml` - SSM parameters, CloudWatch Logs
- `deployment/infrastructure/analytics-pipeline.yaml` - Glue resources
- `deployment/infrastructure/cognito-identity-pool.yaml` - Bedrock model ARNs

**Example:**
```yaml
Resource:
  - !Sub 'arn:${AWS::Partition}:bedrock:*::foundation-model/*'  # ✅ Correct
```

### ✅ S3 URL Construction (Python Code)

**Fixed in:** `source/claude_code_with_bedrock/cli/utils/cloudformation.py:340-347`

```python
if bucket_region.startswith('us-gov-'):
    s3_domain = f"s3.{bucket_region}.amazonaws.com"  # ✅ Correct
elif bucket_region.startswith('cn-'):
    s3_domain = f"s3.{bucket_region}.amazonaws.com.cn"
```

### ✅ Managed IAM Policies

AWS-managed policies like `arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole` do **NOT** need partition variables. AWS handles these automatically. ✅

---

## 3. Other Service Principals - Status: ✅ OK

The following service principals are used and are **correctly identical across all partitions**:

| Service Principal | Used In | Status |
|------------------|---------|--------|
| `ecs-tasks.amazonaws.com` | otel-collector.yaml | ✅ OK |
| `lambda.amazonaws.com` | Multiple templates | ✅ OK |
| `cloudtrail.amazonaws.com` | cognito-identity-pool.yaml | ✅ OK |
| `firehose.amazonaws.com` | analytics-pipeline.yaml | ✅ OK |
| `codebuild.amazonaws.com` | codebuild-windows.yaml | ✅ OK |
| `logs.${AWS::Region}.amazonaws.com` | analytics-pipeline.yaml | ✅ OK |

These service principals use the same format in both Commercial and GovCloud regions.

---

## 4. Recommended Solution

CloudFormation does not provide a built-in pseudo-parameter for service principals. The solution requires using **Conditions** based on `AWS::Partition`.

### Approach 1: Conditional Service Principal (Recommended)

Create conditions to determine the correct Cognito Identity service principal:

```yaml
Conditions:
  IsGovCloudWest: !Equals [!Ref AWS::Region, 'us-gov-west-1']
  IsGovCloudEast: !Equals [!Ref AWS::Region, 'us-gov-east-1']
  IsGovCloud: !Or
    - !Condition IsGovCloudWest
    - !Condition IsGovCloudEast
  IsCommercial: !Not [!Condition IsGovCloud]

Resources:
  AuthenticatedRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Federated: !If
                - IsGovCloudWest
                - cognito-identity-us-gov.amazonaws.com
                - !If
                  - IsGovCloudEast
                  - cognito-identity.us-gov-east-1.amazonaws.com
                  - cognito-identity.amazonaws.com
            Action:
              - 'sts:AssumeRoleWithWebIdentity'
            Condition:
              StringEquals:
                !If
                  - IsGovCloudWest
                  - 'cognito-identity-us-gov.amazonaws.com:aud': !Ref BedrockIdentityPool
                  - !If
                    - IsGovCloudEast
                    - 'cognito-identity.us-gov-east-1.amazonaws.com:aud': !Ref BedrockIdentityPool
                    - 'cognito-identity.amazonaws.com:aud': !Ref BedrockIdentityPool
              'ForAnyValue:StringLike':
                !If
                  - IsGovCloudWest
                  - 'cognito-identity-us-gov.amazonaws.com:amr': authenticated
                  - !If
                    - IsGovCloudEast
                    - 'cognito-identity.us-gov-east-1.amazonaws.com:amr': authenticated
                    - 'cognito-identity.amazonaws.com:amr': authenticated
```

### Approach 2: Multiple Statements (Alternative)

Create separate trust policy statements for each partition:

```yaml
AssumeRolePolicyDocument:
  Version: '2012-10-17'
  Statement:
    # Commercial partition
    - !If
      - IsCommercial
      - Effect: Allow
        Principal:
          Federated: cognito-identity.amazonaws.com
        Action: 'sts:AssumeRoleWithWebIdentity'
        Condition:
          StringEquals:
            'cognito-identity.amazonaws.com:aud': !Ref BedrockIdentityPool
          'ForAnyValue:StringLike':
            'cognito-identity.amazonaws.com:amr': authenticated
      - !Ref AWS::NoValue
    # GovCloud West
    - !If
      - IsGovCloudWest
      - Effect: Allow
        Principal:
          Federated: cognito-identity-us-gov.amazonaws.com
        Action: 'sts:AssumeRoleWithWebIdentity'
        Condition:
          StringEquals:
            'cognito-identity-us-gov.amazonaws.com:aud': !Ref BedrockIdentityPool
          'ForAnyValue:StringLike':
            'cognito-identity-us-gov.amazonaws.com:amr': authenticated
      - !Ref AWS::NoValue
    # GovCloud East
    - !If
      - IsGovCloudEast
      - Effect: Allow
        Principal:
          Federated: cognito-identity.us-gov-east-1.amazonaws.com
        Action: 'sts:AssumeRoleWithWebIdentity'
        Condition:
          StringEquals:
            'cognito-identity.us-gov-east-1.amazonaws.com:aud': !Ref BedrockIdentityPool
          'ForAnyValue:StringLike':
            'cognito-identity.us-gov-east-1.amazonaws.com:amr': authenticated
      - !Ref AWS::NoValue
```

### Approach 3: Nested !If with !Sub (Simplest but Verbose)

Use nested conditionals with string substitution:

```yaml
Conditions:
  IsGovCloudWest: !Equals [!Ref AWS::Region, 'us-gov-west-1']
  IsGovCloudEast: !Equals [!Ref AWS::Region, 'us-gov-east-1']

Mappings:
  ServicePrincipalMap:
    us-gov-west-1:
      CognitoIdentity: cognito-identity-us-gov.amazonaws.com
    us-gov-east-1:
      CognitoIdentity: cognito-identity.us-gov-east-1.amazonaws.com
    default:
      CognitoIdentity: cognito-identity.amazonaws.com

Resources:
  AuthenticatedRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Federated: !FindInMap
                - ServicePrincipalMap
                - !Ref AWS::Region
                - CognitoIdentity
                - !FindInMap [ServicePrincipalMap, default, CognitoIdentity]
```

**Recommendation:** Use **Approach 1** (Conditional Service Principal) as it's explicit, maintainable, and handles all cases correctly.

---

## 5. Testing Strategy

### Pre-Deployment Testing

1. **CloudFormation Validation**
   ```bash
   # Validate templates syntax
   aws cloudformation validate-template \
     --template-body file://deployment/infrastructure/cognito-identity-pool.yaml \
     --region us-east-1

   aws cloudformation validate-template \
     --template-body file://deployment/infrastructure/cognito-identity-pool.yaml \
     --region us-gov-west-1 \
     --profile govcloud
   ```

2. **Linting with cfn-lint**
   ```bash
   cfn-lint deployment/infrastructure/*.yaml
   ```

3. **Unit Test Conditions**
   - Create test stacks in both regions
   - Verify IAM role trust policies resolve correctly

### Deployment Testing

#### Commercial Region (us-east-1)
```bash
poetry run ccwb deploy auth --profile us-east-1
```

**Expected:**
- IAM role trust policy uses `cognito-identity.amazonaws.com`
- Cognito Identity Pool can assume the role
- Bedrock API calls succeed

#### GovCloud Region (us-gov-west-1)
```bash
poetry run ccwb deploy auth --profile gov-west
```

**Expected:**
- IAM role trust policy uses `cognito-identity-us-gov.amazonaws.com`
- Cognito Identity Pool can assume the role
- Bedrock API calls succeed

### Validation Commands

```bash
# Check IAM role trust policy
aws iam get-role \
  --role-name <AuthenticatedRoleName> \
  --query 'Role.AssumeRolePolicyDocument' \
  --region us-gov-west-1 \
  --profile govcloud

# Test Cognito GetId
aws cognito-identity get-id \
  --identity-pool-id <pool-id> \
  --region us-gov-west-1 \
  --profile govcloud

# Test Bedrock access
aws bedrock-runtime invoke-model \
  --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 \
  --body '{"messages":[{"role":"user","content":"Hello"}],"anthropic_version":"bedrock-2023-05-31","max_tokens":10}' \
  --region us-gov-west-1 \
  --profile govcloud \
  output.json
```

---

## 6. Impact Assessment

### Severity: 🔴 **HIGH**

**Without fixing the Cognito Identity service principal issue:**
- ✅ CloudFormation stacks will deploy successfully
- ❌ IAM role assumption will fail
- ❌ Users cannot authenticate via Cognito Identity Pool
- ❌ No access to Bedrock in GovCloud
- ❌ Application is non-functional in GovCloud

**With the fix:**
- ✅ Full functionality in both Commercial and GovCloud
- ✅ Seamless deployment across partitions
- ✅ Proper authentication flow
- ✅ Bedrock access works correctly

---

## 7. Additional Considerations

### Future Partitions

If AWS introduces new partitions (e.g., AWS EU Sovereign Cloud), the solution must be updated to handle new service principal formats.

### China Region Support

While `${AWS::Partition}` handles ARNs correctly for China (`aws-cn`), Cognito Identity is **not available** in China regions as of 2025-11-22. No additional changes needed for China partition at this time.

### Cognito User Pool Provider

The Cognito User Pool provider format in `cognito-identity-pool.yaml:105` is already correct:
```yaml
ProviderName: !Sub 'cognito-idp.${AWS::Region}.amazonaws.com/${CognitoUserPoolId}'
```

This format works correctly in GovCloud (e.g., `cognito-idp.us-gov-west-1.amazonaws.com/...`).

---

## 8. Action Items

### Immediate (Required for GovCloud Support)

- [ ] Update all 6 CloudFormation templates with partition-aware Cognito Identity service principals
- [ ] Add Conditions section to each affected template
- [ ] Update both `AuthenticatedRole` and `UnauthenticatedRole` trust policies
- [ ] Test deployment in us-east-1 (Commercial)
- [ ] Test deployment in us-gov-west-1 (GovCloud)
- [ ] Update `TESTING_PARTITION_SUPPORT.md` with new testing procedures

### Recommended (Best Practices)

- [ ] Create a reusable CloudFormation snippet/module for the Cognito Identity trust policy
- [ ] Add automated tests to verify service principal resolution
- [ ] Document the partition support approach in architecture docs
- [ ] Add CloudFormation validation to CI/CD pipeline

---

## 9. Conclusion

The repository has made good progress on partition support by implementing `${AWS::Partition}` for resource ARNs and handling S3 endpoints correctly. However, **critical work remains** to support GovCloud:

1. **30 occurrences** of hardcoded `cognito-identity.amazonaws.com` must be made partition-aware
2. This requires adding **Conditions** and conditional logic to 6 CloudFormation templates
3. Without this fix, the application will deploy but **fail to function** in GovCloud

**Recommendation:** Implement Approach 1 (Conditional Service Principal) across all affected templates before merging this branch.

---

## References

- [Amazon Cognito in AWS GovCloud (US)](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-cog.html)
- [CloudFormation Pseudo Parameters](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/pseudo-parameter-reference.html)
- [AWS Partitions](https://docs.aws.amazon.com/general/latest/gr/aws-arns-and-namespaces.html)
