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

## Auth-Type Parity

Beyond Go↔Python, features must also work across all 3 auth types:
- **OIDC** — JWT available, use Bearer token
- **IDC** — No JWT, use SigV4 with ambient AWS credentials
- **none** — No identity, skip or warn

If a feature works for OIDC but not IDC, it's incomplete. Check:
- Does the Go handler have the same IDC fallback as Python?
- Does `--quota-status` / monitoring work without a JWT?
- Are error messages clear about which auth type is needed?

*Issues: #204 (session name truncation), #58 (recursion)*
