# Auth Type Compatibility

## Rule
Use `profile.effective_auth_type` property. Never assume `auth_type` exists in saved configs.

## Why
Older profiles only have `sso_enabled` boolean. We need backward compatibility for the `sso_enabled` → `auth_type` migration.

## Examples
```python
# ✅ Correct - handles both old and new configs
auth_type = profile.effective_auth_type  # returns "oidc", "idc", or "none"

# ❌ Wrong - crashes on old configs
if profile.auth_type == "oidc":  # KeyError if auth_type doesn't exist
```

## Backward Compatibility Mapping
- `sso_enabled=True` → "oidc"
- `sso_enabled=False` → "none"
- `auth_type="idc"` → IDC (new, no legacy mapping needed)

## IDC as First-Class Path

IDC is now fully supported (not "coming soon"). When adding features:
- IDC has no JWT — use SigV4 for API auth, STS identity for attribution
- IDC usernames come from IAM ARN session name (may not contain `@`)
- IDC has quota support via SigV4-signed requests to API Gateway
- IDC has OTEL attribution via `GetCallerIdentity` → ARN parsing

## Related Issues
#285, #287, #288, #304, #337, #430, #454, #456