---
name: check-cfn
description: "Validate CloudFormation templates with cfn-lint and check for common issues like hardcoded partitions, overly permissive IAM, or missing outputs. Use when editing CF templates, before deploying, or when troubleshooting infrastructure issues."
user-invocable: true
argument-hint: "[template-name]"
---

# CloudFormation Template Checker

Validate CloudFormation templates thoroughly. Arguments: $ARGUMENTS

## Determine Scope

- No arguments: validate ALL templates in `deployment/infrastructure/`
- Template name: validate just that template (with or without `.yaml` suffix)

## Validation Steps

1. **cfn-lint** — structural and syntax validation:
   ```bash
   cd source && poetry run cfn-lint ../deployment/infrastructure/<template-or-*>.yaml
   ```

2. **Manual checks** — grep for common issues:

   a. **Hardcoded partitions** — should use `${AWS::Partition}`:
   ```
   grep -n "arn:aws:" deployment/infrastructure/<template>.yaml
   ```
   Any match (outside comments) is a bug — GovCloud compatibility requires `${AWS::Partition}`.

   b. **Overly permissive IAM** — `Resource: "*"` without justification:
   ```
   grep -n 'Resource.*\*' deployment/infrastructure/<template>.yaml
   ```

   c. **Missing DeletionPolicy** on stateful resources (DynamoDB, S3, etc.)

   d. **Missing Outputs** — templates should export key resource ARNs

3. **Cross-reference** — if this template references other stacks via `Fn::ImportValue`, verify those stacks export the expected values.

## Output Format

```
Template: bedrock-auth-okta.yaml
  [PASS] cfn-lint — no errors
  [PASS] Partition — uses ${AWS::Partition} throughout
  [WARN] IAM — line 45: Resource "*" on bedrock:InvokeModel (acceptable for cross-region)
  [PASS] Outputs — exports RoleArn, ProviderArn

Overall: 0 errors, 1 warning
```
