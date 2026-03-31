---
paths:
  - "source/credential_provider/**/*.py"
---

# Credential Provider Security Rules

## Security Requirements
- NEVER log, print, or write tokens (access, refresh, ID) to files or stdout
- NEVER hardcode secrets, client secrets, or credentials
- Token output goes ONLY through the AWS credential process JSON protocol
- Use PKCE (Proof Key for Code Exchange) for all OAuth2 flows — no implicit grants

## OAuth2/OIDC Flow
1. Generate PKCE code_verifier + code_challenge
2. Open browser to IdP authorization endpoint
3. Listen on `http://localhost:8400/callback` for the redirect
4. Exchange authorization code for tokens (with code_verifier)
5. Federate tokens via STS AssumeRoleWithWebIdentity or Cognito
6. Return temporary AWS credentials as JSON to stdout

## Credential Storage
- `keyring`: OS-native secure storage (macOS Keychain, Windows Credential Manager)
- `session`: Encrypted files in `~/.aws/` with restrictive permissions (0600)
- Never store plaintext credentials on disk

## Testing
- Mock all HTTP calls (no real IdP communication in tests)
- Mock keyring/session storage
- Test token refresh, expiry, and cache invalidation paths
- Verify credential JSON output format matches AWS CLI spec
