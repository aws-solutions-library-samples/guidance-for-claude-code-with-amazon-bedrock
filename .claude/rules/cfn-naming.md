# CloudFormation Templates

## Naming
- No hardcoded physical resource `Name` on resources that may be conditionally created or replaced (ALBs, ECS services, target groups). Let CloudFormation auto-generate.
- When a name IS needed, use `!Sub '${AWS::StackName}-*'` for uniqueness.
- Hardcoded names cause `AlreadyExists` failures during stack updates (CF creates-before-deletes).

## Before Modifying Templates
- Run `cfn-lint deployment/infrastructure/<template>.yaml`
- New parameters MUST have `Default` values (existing stacks won't pass new params on update)
- Conditions must handle both true and false paths (use `!Ref AWS::NoValue` for the "off" path)
- Never rename logical IDs of stateful resources (S3, DynamoDB, ECS) — causes resource replacement and data loss

## Parameter Safety
```yaml
# ✅ Correct - existing stacks won't break
Parameters:
  NewFeatureEnabled:
    Type: String
    Default: 'false'  # Safe default
    AllowedValues: ['true', 'false']

# ❌ Wrong - breaks existing stacks on update
Parameters:
  RequiredNewParam:
    Type: String
    # No default! Existing stacks fail on update
```

## Conditional Resources
```yaml
# ✅ Correct - gated resource with NoValue fallback
LambdaConfig: !If
  - FeatureEnabled
  - PreTokenGeneration: !GetAtt MyFunction.Arn
  - !Ref AWS::NoValue

# ❌ Wrong - no false path
LambdaConfig: !If
  - FeatureEnabled
  - PreTokenGeneration: !GetAtt MyFunction.Arn
  # Missing else!
```

## Related Issues
#86, #312, #398, #573, #603