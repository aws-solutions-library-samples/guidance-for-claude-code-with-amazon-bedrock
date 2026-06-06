# OAuth Callback Safety

## Rule
- Don't shut down server after first request (could be favicon)
- Use port locking, not TOCTOU checks
- WSL + VPN may block localhost forwarding

## Why
OAuth callback servers can receive multiple requests (favicon, actual callback). Early shutdown causes auth failures. WSL with VPN breaks localhost forwarding, preventing callback completion.

## Implementation
- Wait for actual OAuth callback, not just any HTTP request
- Use proper port locking mechanisms
- Document WSL/VPN workarounds for users

## Examples
```python
# ✅ Correct - wait for actual callback
def handle_callback():
    while True:
        request = server.get_request()
        if 'code=' in request.query_string:  # Actual OAuth callback
            return process_callback(request)
        # Ignore favicon and other requests

# ❌ Wrong - shuts down on first request
def handle_callback():
    request = server.get_request()  # Could be favicon
    server.shutdown()  # Too early!
```

## Related Issues
#269, #270, #393, #428