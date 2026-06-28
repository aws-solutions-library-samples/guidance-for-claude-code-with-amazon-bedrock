---
description: Naming conventions and user-facing label clarity for docs, CLI output, and issue templates
---

## Product naming
- Use "Claude Desktop" as the primary name in user-facing docs and PR descriptions
- "Cowork" is the brand name (capital C, one word) — acceptable as a shorter reference
- Never use "CoWork" (camelCase) — the correct form is "Cowork"
- "Claude Desktop on 3P" or "Claude Desktop (third-party)" for the Bedrock-backed variant

## User-facing labels (CLI output, doctor checks, issue templates)
- Use full descriptive labels, not internal field names:
  - "desktop config mode" not "config_mode"
  - "bootstrap server" not "bootstrap"
  - "OIDC client secret" not "client_secret_arn"
  - "OIDC discovery endpoints" not "oidc_endpoints"
  - "Claude Desktop config delivery" not "desktop delivery"
- In summary banners, prefix with context: "Desktop Config:" not just "Desktop:"
- In doctor checks, make each line self-explanatory without needing to read other lines
- Avoid ARN references in user-facing messages — say "configured (SecretsManager)" instead
- When referencing the bootstrap feature, always say "bootstrap server" (not just "bootstrap")
