# Token Endpoint Single Builder

## Rule
Any code that constructs a provider's token endpoint URL MUST use
`provider.TokenEndpointURL()`. Never inline URL building with
`providerDomain + provCfg.TokenEndpoint` concatenation.

## Why
Azure's `provider_domain` is stored WITH a trailing `/v2.0`
(`login.microsoftonline.com/<tenant>/v2.0`) while its token endpoint
already carries the version segment (`/oauth2/v2.0/token`). Naive
concatenation produces `.../v2.0/oauth2/v2.0/token` — a doubled segment
Azure rejects with HTTP 404.

Google uses absolute URLs (`https://oauth2.googleapis.com/token`) that
must be returned as-is, not prefixed with a domain.

These quirks are handled in exactly one place: `provider.TokenEndpointURL()`
(in `internal/provider/endpoints.go`). Using it everywhere guarantees the
auth flow and refresh flow can never drift apart.

## Anti-Pattern
```go
// ❌ Wrong — inline URL building (Azure 404, Google double-prefix)
provCfg := provider.ConfigFor(providerType, oktaAuthServerID)
tokenURL = "https://" + providerDomain + provCfg.TokenEndpoint

// ✅ Correct — shared builder handles all provider quirks
tokenURL = provider.TokenEndpointURL(providerType, oktaAuthServerID, providerDomain)
```

## Callers (must all use the shared builder)
- `oidc/flow.go` — browser authorization-code exchange
- `tryRefreshToken()` in main.go — silent refresh
- `refreshIDTokenOnly()` — monitoring token refresh (when added)
- Any future token endpoint caller

## Related
- PR #666 (introduced `TokenEndpointURL` + `NormalizeDomain`)
- `issuer-url-format.md` — same class of provider-specific URL quirks
- `credential-flow.md` — runtime flow showing where refresh happens
