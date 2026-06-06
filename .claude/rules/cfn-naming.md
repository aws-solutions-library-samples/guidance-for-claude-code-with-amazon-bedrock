# CloudFormation Naming

## Rule
- No hardcoded resource names
- Use `!Sub '${AWS::StackName}-*'`
- All templates must pass `cfn-lint`
- Use `Condition` + `aws:RequestedRegion` for region scoping

## Why
Hardcoded names break multi-profile deployments when users try to deploy the same template multiple times. Dynamic naming based on stack name ensures uniqueness.

## Examples
```yaml
# ❌ Wrong - breaks multi-profile deployments
Resources:
  TargetGroup:
    Type: AWS::ElasticLoadBalancingV2::TargetGroup
    Properties:
      Name: otel-collector-tg

# ✅ Correct - unique per stack
Resources:
  TargetGroup:
    Type: AWS::ElasticLoadBalancingV2::TargetGroup
    Properties:
      Name: !Sub '${AWS::StackName}-tg'
```

## Related Issues
#312, #398