# Quota Auth Requirements

## Rule
Quota enforcement works for OIDC and IDC. Only skip for `auth_type == "none"`.

## Auth Paths for Quota

| Auth Type | Quota API Auth | User Identity Source |
|-----------|---------------|---------------------|
| **OIDC** | Bearer JWT in `Authorization` header | `email` claim from JWT |
| **IDC** | SigV4-signed request (IAM auth) | Email from IAM ARN session name |
| **none** | Not available | No identity → skip quota |

## Implementation
- **Init wizard:** offer quota for OIDC and IDC. Skip only for "none".
- **Deploy:** deploy quota stack for OIDC and IDC. Skip with warning for "none".
- **IDC specifics:**
  - API Gateway must have IAM authorization enabled (not just JWT)
  - IAM callers need `execute-api:Invoke` permission on the quota API
  - IDC usernames may not contain `@` — resolve them as valid identity regardless

## Examples
```python
# ✅ Correct - quota works for OIDC and IDC
if profile.effective_auth_type in ("oidc", "idc"):
    # Deploy quota stack
else:
    logger.warning("Skipping quota - requires OIDC or IDC authentication")

# ❌ Wrong - blocks IDC users from quota
if profile.effective_auth_type == "oidc":
    # Deploy quota stack (misses IDC!)
```

## Related Issues
#287, #337, #454, #458, #524, #597, #598, #611
