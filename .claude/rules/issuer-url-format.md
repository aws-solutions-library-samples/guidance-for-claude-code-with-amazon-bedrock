# Issuer URL Format

## Rule
Issuer URL format is provider-specific. Follow exact format requirements for each provider.

## Why
Mismatch causes JWT validation failures at ALB or API Gateway level. Each provider has strict requirements about trailing slashes and URL structure.

## Provider Formats
| Provider | Issuer URL format | Trailing slash? |
|----------|------------------|----------------|
| Auth0 | `https://company.auth0.com/` | ✅ Required |
| Azure | `https://login.microsoftonline.com/{tenant}/v2.0` | ❌ Must NOT have |
| Okta | `https://company.okta.com/oauth2/default` | ❌ No |
| Cognito | `https://cognito-idp.{region}.amazonaws.com/{pool-id}` | ❌ No |

## Examples
```python
# ✅ Correct - Auth0 requires trailing slash
issuer = "https://company.auth0.com/"

# ❌ Wrong - Auth0 without trailing slash
issuer = "https://company.auth0.com"

# ✅ Correct - Azure must NOT have trailing slash
issuer = "https://login.microsoftonline.com/tenant-id/v2.0"

# ❌ Wrong - Azure with trailing slash
issuer = "https://login.microsoftonline.com/tenant-id/v2.0/"
```

## Related Issues
#97, #115