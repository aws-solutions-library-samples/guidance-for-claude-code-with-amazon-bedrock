# IAM Actions

## Rule
Use `bedrock:` namespace only for Bedrock IAM actions.

## Why
The `bedrock-runtime:` prefix doesn't exist in IAM. It's been a persistent source of broken templates and deploy failures.

## Examples
```yaml
# ❌ Wrong - causes deploy failures
- bedrock-runtime:InvokeModel
- bedrock-runtime:InvokeModelWithResponseStream

# ✅ Correct
- bedrock:InvokeModel
- bedrock:InvokeModelWithResponseStream
```

## Related Issues
#375, #63

## See Also
.claude/rules/aws-identifiers.md