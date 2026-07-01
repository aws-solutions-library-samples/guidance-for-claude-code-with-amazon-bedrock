# AWS Identifiers

## Rule
Never hand-build an ARN or resource ID that an API response or CloudFormation
output already returns. Read it from the source of truth.

## Why
AWS adds parts you can't predict - Secrets Manager appends a random 6-char
suffix to secret ARNs (`...-FhLi4n`); many IDs are server-assigned. A
formatted `f"arn:...:{name}"` silently omits them, and downstream consumers
(e.g. `{{resolve:secretsmanager:<arn>}}` in an ALB listener) fail with
ResourceNotFoundException at deploy time.

## Examples
```python
# ❌ Wrong - omits the random suffix
secret_arn = f"arn:aws:secretsmanager:{region}:{account_id}:secret:{name}"

# ✅ Correct - use the API response
resp = client.create_secret(Name=name, SecretString=val)   # or update_secret
secret_arn = resp["ARN"]
# ...or recover it when you have no response:
secret_arn = client.describe_secret(SecretId=name)["ARN"]
```

The escape hatch for a genuine last-resort fallback is a plain
`# allow-handbuilt-arn` comment on the line (not a `# noqa:` code, which ruff
would reject and `ruff --fix` could strip).

## Related
- Sibling of .claude/rules/iam-actions.md (bedrock-runtime: prefix). Same class:
  AWS strings written from memory instead of from the source of truth.
- Issue: distribution HTTPSListener ResourceNotFoundException (init secret ARN).
