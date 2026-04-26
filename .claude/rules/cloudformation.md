---
paths:
  - "deployment/infrastructure/**/*.yaml"
---

# CloudFormation Template Rules

## Format & Validation
- Templates use YAML format (converted to JSON via cfn-flip during deployment)
- Always validate after editing: `poetry run cfn-lint deployment/infrastructure/<template>.yaml`
- Use `cfn-lint` annotations to suppress false positives, not to hide real issues

## Multi-Partition Support (CRITICAL)
- Always use `!Sub "arn:${AWS::Partition}:..."` instead of hardcoding `arn:aws:`
- GovCloud service principals differ: e.g., `cognito-identity-us-gov.amazonaws.com`
- Use `AWS::Partition`, `AWS::Region`, `AWS::AccountId` pseudo-parameters
- Test mental model: "Would this template deploy in both `aws` and `aws-us-gov`?"

## IAM Policies
- Follow least-privilege: scope resources to specific ARNs, not `*`
- Use conditions where applicable (e.g., `StringEquals` on tags)
- Session tags (`aws:PrincipalTag/*`) enable CloudTrail user attribution

## Naming Conventions
- Stack parameters: PascalCase (e.g., `IdentityPoolId`)
- Logical resource IDs: PascalCase (e.g., `BedrockAccessRole`)
- Output export names: `${AWS::StackName}-<resource>` pattern

## Template Categories
- `bedrock-auth-*.yaml`: Provider-specific authentication (one per IdP)
- `cognito-*.yaml`: Cognito-specific resources
- `*-distribution.yaml`: Package distribution infrastructure
- Monitoring templates: `otel-collector`, `claude-code-dashboard`, `analytics-pipeline`
