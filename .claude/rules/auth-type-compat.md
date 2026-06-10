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

## Related Issues
#285, #287, #288, #304, #337, #430, #454, #456