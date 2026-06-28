# CLAUDE.md — CloudFormation Templates

## Quick Commands

```bash
cfn-lint deployment/infrastructure/*.yaml    # Validate all templates
cfn-lint deployment/infrastructure/my-stack.yaml  # Validate single template
```

## Key Rules

### Partition & Region
- **Always** use `!Sub "arn:${AWS::Partition}:..."` — never hardcode `arn:aws:`.
- This ensures GovCloud (`aws-us-gov`) and China (`aws-cn`) compatibility.
- Use `${AWS::Region}`, `${AWS::AccountId}` — never hardcode account/region.

### Conditions Pattern
- Name conditions positively: `HasOidcAuth`, `HasQuotaEnabled` (not `NoOidc`).
- Empty string = disabled: `!Equals [!Ref ParamName, ""]` for optional params.
- Use `!If [ConditionName, TrueValue, FalseValue]` — never duplicate resources.

### Route-Key Conflicts
- **One resource per route-key.** Don't create two `AWS::ApiGatewayV2::Route` for the same path.
- Use `!If` inside a single route resource to switch `AuthorizationType` or `Target`.
- See issue #682 for the pattern that caused a production regression.

### IAM Permissions
- Exact actions only — no `s3:*` or `Action: "*"`.
- Scope `Resource` to the specific ARN (use `!Sub` with resource refs).
- Match IAM actions to actual API calls in the Lambda code.
- See `.claude/rules/iam-actions.md`.

### Stack Ordering
- Destroy order matters — dependent stacks must be destroyed first.
- See `.claude/rules/stack-ordering.md` for the canonical order.
- New stacks: add to both `VALID_STACKS` and `DESTROYABLE_STACKS` in `deploy.py`.

### Parameters
- New parameters must have `Default` values (backwards compat with existing deployments).
- Use `AllowedValues` where the set is finite (auth modes, regions).
- Mark sensitive params with `NoEcho: true`.

### Outputs & Exports
- Conditional outputs need `Condition:` — don't export values that might not exist.
- Export names: `${AWS::StackName}-ResourceName` format.

## Common Pitfalls
- Don't use `DependsOn` for implicit dependencies (Ref/GetAtt already creates them).
- Don't put `!Sub` inside `!If` values that contain no variables (cfn-lint error).
- Don't create `DeletionPolicy: Retain` without documenting manual cleanup steps.
- Don't reference `AWS::StackName` in resource names if you plan nested stacks.
