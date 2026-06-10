# Review Tiers

Changes to critical components require proportionally higher testing
and review standards. This prevents regressions in paths that affect
all users.

## Tier 1 — Critical (all users affected if broken)

**Files:**
- `source/claude_code_with_bedrock/config.py`
- `source/claude_code_with_bedrock/cli/commands/deploy.py`
- `source/go/cmd/credential-process/main.go`
- `source/go/internal/config/config.go`
- `source/go/cmd/otel-helper/main.go`
- `source/go/internal/otel/extract.go`, `headers.go`
- `source/go/internal/federation/sts.go`
- `deployment/infrastructure/bedrock-auth-*.yaml`

**Requirements:**
- Regression test for every changed code path
- Backward-compat test (old configs still load and work)
- Cross-platform CI must pass (no admin merge override)
- Parity check if touching Go ↔ Python equivalents
- Test with all auth types: oidc, idc, none

## Tier 2 — High (subset of users affected)

**Files:**
- `source/claude_code_with_bedrock/cli/commands/init.py`
- `source/claude_code_with_bedrock/cli/commands/package.py`
- `source/credential_provider/__main__.py`
- `deployment/infrastructure/otel-collector.yaml`
- `deployment/infrastructure/quota-monitoring.yaml`
- `source/go/internal/oidc/`, `source/go/internal/federation/`

**Requirements:**
- Regression test required
- cfn-lint for template changes
- Test on Windows if touching credential/packaging paths

## Tier 3 — Standard (limited blast radius)

**Files:** docs, dashboards, analytics, tests, CI workflows

**Requirements:**
- Tests must pass
- No regression test required (unless fixing a bug)
