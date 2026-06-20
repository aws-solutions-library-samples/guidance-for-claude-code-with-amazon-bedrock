# Credential Flow

## Rule
Understand the runtime credential flow before modifying auth, quota, or caching logic.

## Flow

```
AWS SDK → credential-process [Go or Python]
  1. Read cached credentials (file or keyring)
  2. If valid + not expired → return immediately (fast path, ~5ms)
  3. If expired → try silent refresh (refresh_token exchange, no browser)
  4. If no refresh_token → OIDC browser flow (or IDC passthrough)
  5. Exchange token → STS AssumeRoleWithWebIdentity → temporary credentials
  6. Check quota (if configured) → blocked? exit non-zero
  7. Save credentials to cache
  8. Emit OTEL attribution headers to cache file
  9. Print JSON to stdout → AWS SDK uses credentials
```

## Critical Constraints

- **stdout is sacred:** Only the final JSON credentials may be printed to stdout. Any other output breaks the AWS SDK parser. Use stderr for messages.
- **Exit codes:** 0 = valid credentials on stdout. Non-zero = failure (SDK retries or errors).
- **Performance:** This runs on EVERY AWS API call when credentials expire. Keep the hot path (step 2) under 20ms.
- **Concurrency:** Multiple processes may call credential-process simultaneously. Use port-locking to prevent parallel auth flows.

## Common Mistakes

```python
# ❌ Wrong - breaks AWS SDK
print("Authenticating...")  # stdout pollution
print(json.dumps(credentials))

# ✅ Correct - messages to stderr only
print("Authenticating...", file=sys.stderr)
print(json.dumps(credentials))  # only JSON on stdout
```

## Quota Integration

Quota check happens AFTER auth but BEFORE outputting credentials:
- If quota blocks → exit non-zero (credential-process contract: no JSON = failure)
- If quota warns → print warning to stderr, still output credentials
- Quota check uses the same token (OIDC: Bearer, IDC: SigV4)

## OTEL Attribution

After successful auth, otel-helper updates the attribution cache:
- Extracts user info from JWT claims (OIDC) or ARN (IDC)
- Writes headers to `~/.ccwb/cache/<profile>-otel-headers.json`
- Central collector reads these via ALB forwarded headers
- Sidecar collector reads from local cache file

## Related Rules
- `otel-attribution-chain.md` — header format and token lifecycle
- `quota-requires-oidc.md` — which auth types support quota
- `credential-helper-parity.md` — Go and Python must match
