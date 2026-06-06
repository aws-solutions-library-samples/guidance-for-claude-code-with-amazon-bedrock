# Quota Requires OIDC

## Rule
Quota enforcement needs JWT from OIDC provider. Skip for `auth_type in ("idc", "none")`.

## Why
Quota monitoring depends on JWT tokens for user identification. IDC and "none" auth types don't provide JWTs, so quota stacks will fail to deploy.

## Implementation
- **Init wizard:** don't offer quota when SSO disabled
- **Deploy:** skip quota stack with warning, don't let CloudFormation fail

## Examples
```python
# ✅ Correct - guard quota features
if profile.effective_auth_type == "oidc":
    # Deploy quota stack
else:
    logger.warning("Skipping quota - requires OIDC authentication")

# ❌ Wrong - will cause CloudFormation failures
# Always deploy quota regardless of auth type
```

## Related Issues
#287, #337, #454, #458