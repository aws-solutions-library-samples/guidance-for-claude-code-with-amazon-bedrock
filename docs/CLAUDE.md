# CLAUDE.md — Documentation

## Naming Conventions
- **Claude Desktop** (not "CoWork", "Cowork", "Co-Work", or "Claude for Desktop")
- **Claude Code** (not "the CLI", "ccwb CLI", or "Claude Code CLI")
- **Historical Usage Analytics** (not just "Analytics")
- **IAM Identity Center** or **IDC** (not "SSO" in new docs)
- **Cognito** — mark as "legacy" when referencing old auth flows

## Key Rules

### Don't Duplicate
- README.md is the entry point — keep it concise (users skim).
- Detailed docs live in `assets/docs/` — link from README, don't inline.
- If content exists in another doc, link to it — don't copy.

### Security in Docs
- **Never** include real AWS account IDs, internal URLs, or API keys in examples.
- Use placeholder format: `123456789012`, `https://your-api.execute-api.region.amazonaws.com`
- Redact in code samples: `export OIDC_ISSUER_URL=https://your-idp.example.com`

### Code Samples
- Test that code samples actually work (or clearly mark as pseudocode).
- Include the auth mode each sample applies to (OIDC/IDC/both).
- Show both success and error cases where relevant.

### Changelog
- Update `CHANGELOG.md` for user-facing changes only (not internal refactors).
- Format: `## [version] - YYYY-MM-DD` with Added/Changed/Fixed/Removed sections.
- Link to PR numbers for traceability.

## Common Pitfalls
- Don't create new top-level docs files — use `assets/docs/` subdirectory.
- Don't document internal implementation details in user-facing docs.
- Don't use em-dashes (—) in file paths or command examples.
- Don't reference branch names (`beta`) in user docs — users see `main` releases only.
