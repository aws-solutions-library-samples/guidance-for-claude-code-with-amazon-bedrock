# Keyring Chunking

## Rule
Windows Credential Manager has a 1280-byte limit per entry. Tokens >1280 bytes must be chunked.

## Why
Large tokens (common with some OIDC providers) exceed Windows Credential Manager's per-entry limit, causing storage failures and authentication issues.

## Implementation
- Test with realistic token sizes (not just small test tokens)
- Implement chunking logic for tokens >1280 bytes
- `Path.home()` uses USERPROFILE on Windows (not HOME)

## Examples
```python
# ✅ Correct - check token size and chunk if needed
if len(token) > 1280:
    # Implement chunking logic
    store_chunked_token(key, token)
else:
    keyring.set_password(service, key, token)

# ❌ Wrong - will fail with large tokens
keyring.set_password(service, key, large_token)  # Fails if >1280 bytes
```

## Related Issues
#348, #381, #427, #453