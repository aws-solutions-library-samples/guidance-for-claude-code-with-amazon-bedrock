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

## Auth Flow Parity

Every user-facing feature that depends on identity or authentication must
work (or gracefully degrade) across all three auth types.

| Auth Type | Email source | Token available | Quota API auth |
|---|---|---|---|
| OIDC | JWT `email` claim | Yes (ID token) | Bearer JWT |
| IDC | IAM ARN session name | No | SigV4 |
| none | Not available | No | Not available |

### Graceful Degradation Pattern
```python
if auth_type == "oidc":
    # Full feature with JWT identity
elif auth_type == "idc":
    # Feature with IAM identity (may be limited)
else:
    # Skip or warn: "Requires OIDC or IDC authentication"
```

### Red Flags in PRs
- Hard-coded `token_claims["email"]` without `.get()` fallback
- New Bearer-only API call without IDC SigV4 alternative
- Feature that silently fails for IDC users without warning
- Missing test for `auth_type != "oidc"`

## Related Issues
#285, #287, #288, #304, #337, #430, #454, #456