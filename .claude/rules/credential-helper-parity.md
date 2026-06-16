# Credential Helper Parity (Go ↔ Python)

The credential-process has Go and Python variants. Both must produce
identical outputs for the same inputs.

## Critical contract

- `buildSessionName()` (Go) and session_name logic (Python) must use
  the same claim priority: `email` → `sub` → `"claude-code"`
- Same sanitization regex: `[^\w+=,.@-]` → `"-"`
- Same length limits: email = 64 chars, sub = 32 chars
- Same fallback format: `"claude-code-{sub_sanitized}"`

## Why

The STS RoleSessionName appears in CUR 2.0 `line_item_iam_principal`.
If Go emits `alice@acme.com` but Python emits `claude-code-alice`, cost
attribution splits the same user into two identities.

## Testing

Any change to either variant requires a parity test:
- Feed identical JWT claims to both → assert identical session name
- Edge cases: no email, no sub, pipe-delimited sub (`auth0|12345`), >64 char email
- Verify sanitization produces identical output across variants

*Issues: #204 (session name truncation), #58 (recursion)*

## Provider Detection Parity

When adding a new OIDC provider:
1. Add to Python `PROVIDER_CONFIGS` dict
2. Add to Go's provider detection in `main.go` (`_determine_provider_type` equivalent)
3. Same hostname patterns and domain matching in both

Example: PR #563 added Google to Go after it was already in Python — this gap should never happen.
