# CLAUDE.md

Project rules for AI coding agents. Detailed rules in `.claude/rules/`.
Subdirectory `CLAUDE.md` files provide focused context per component:
- `source/CLAUDE.md` — Python CLI, tests, config patterns
- `source/go/CLAUDE.md` — Go binaries, --explain contract, Windows guards
- `deployment/CLAUDE.md` — CloudFormation templates, IAM, conditions
- `deployment/infrastructure/lambda-functions/CLAUDE.md` — Lambda auth, response patterns
- `docs/CLAUDE.md` — Documentation naming, security, structure

## Key Principles

1. **Auth path coverage:** Features touching identity must work across OIDC, IDC, and "none" — or fail clearly.
2. **Collector mode awareness:** Telemetry changes must work in both central (ECS/ALB) and sidecar (local) modes.
3. **Surface compatibility:** Claude Code (CLI) and Claude Desktop (CoWork 3P) share credential-process, OTEL, and quota.
4. **Backwards compatibility:** New fields must have defaults. Old configs must load. Existing deployments must not break on update.
5. **Regression coverage:** Every bug fix includes a test that fails without the fix and passes with it.
6. **Cross-platform:** Windows, macOS, and Linux are all first-class. CI blocks on Windows failures.

## Repository

AWS guidance for Claude Code with Amazon Bedrock. Python CLI (`ccwb`) + Go credential-process binary + CloudFormation templates.

## Auth Modes

| Mode | Identity | Quota | OTEL |
|------|----------|-------|------|
| **OIDC** | JWT email | Bearer | Full |
| **IDC** | IAM ARN | SigV4 | Via STS |
| **none** | Hashed principal | ❌ | Anonymous |

## Branch Strategy

- Target: `beta` (not `main`). Rebase before PRs. `main` is release-only.

## Architecture

```
ccwb init → profile.json → ccwb deploy → CloudFormation
                         → ccwb package → credential-process (Go) + otel-helper
```

### Runtime Flow (credential-process)
```
AWS SDK calls credential-process
  → read cache → [valid?] → return cached credentials
  → [expired?] → try silent refresh (refresh_token)
  → [no token?] → OIDC browser flow or IDC passthrough
  → check quota with id_token → [blocked?] → exit non-zero
  → STS AssumeRoleWithWebIdentity → credentials
  → emit OTEL attribution headers → cache → stdout JSON
```

### Key Files
- `source/credential_provider/__main__.py` — Python credential provider
- `source/go/cmd/credential-process/main.go` — Go credential provider
- `source/otel_helper/__main__.py` — OTEL header generation
- `source/claude_code_with_bedrock/cli/commands/` — CLI commands
- `source/claude_code_with_bedrock/config.py` — Profile dataclass
- `source/go/internal/config/config.go` — Go config struct
- `deployment/infrastructure/` — CloudFormation templates

## Testing

- `cd source && poetry run pytest tests/ -q` before pushing
- Must pass Linux, macOS, AND Windows (CI matrix)
- Windows tests are blocking
- Every fix needs a regression test

## Documentation

- Update docs only when behavior changes — don't rewrite for style alone
- Keep README concise (users skim, not read). Detail belongs in `assets/docs/`
- Code changes that affect user-facing behavior should update docs in the same PR
- Don't create docs PRs that duplicate information already in other docs files
