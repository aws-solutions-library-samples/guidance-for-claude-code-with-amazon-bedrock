# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Project rules for AI coding agents. Detailed, topic-specific rules live in `.claude/rules/` (auto-loaded). This file is the entry point.

## Repository
Enterprise deployment guidance for Claude Code / Claude Cowork on Amazon Bedrock via existing OIDC IdPs (Okta, Azure AD, Auth0, Google, Cognito) or IAM Identity Center. Three artifacts work together:
- **Python CLI (`ccwb`)** — deployment/management wizard (`source/claude_code_with_bedrock/`)
- **Go binaries** — `credential-process` (AWS SDK credential provider) and `otel-helper` (telemetry headers), in `source/go/`
- **CloudFormation templates** — federation, monitoring, quota infra, in `deployment/infrastructure/`

## Architecture
```
ccwb init (wizard) → config.yaml → ccwb deploy → CloudFormation stacks (IAM/OIDC, OTEL, quota)
                                  → ccwb package → config.json + Go binary → ~/.aws credential-process
```
The Go `credential-process` is invoked **by** the AWS SDK to mint temporary Bedrock credentials from an OIDC token. `otel-helper` emits per-user telemetry headers for cost attribution and quota enforcement.

### Key files (see `.claude/rules/review-tiers.md` for criticality tiers)
- `source/claude_code_with_bedrock/config.py` — `Profile` dataclass (must stay in sync with Go `ProfileConfig`)
- `source/claude_code_with_bedrock/cli/__init__.py` — CLI command registration (cleo)
- `source/claude_code_with_bedrock/cli/commands/{init,deploy,package,distribute,test,quota}.py` — main commands
- `source/go/cmd/credential-process/main.go` — Go credential provider (STS/Cognito federation)
- `source/go/cmd/otel-helper/main.go`, `source/go/internal/otel/` — telemetry header extraction
- `source/go/internal/config/config.go` — Go config struct (mirrors Python `Profile`)
- `deployment/infrastructure/bedrock-auth-*.yaml` — per-provider federation templates

## Common Commands
All Python commands run from `source/` (Poetry project). Go commands from `source/go/`.

```bash
# Python — setup, test, lint (from source/)
poetry install --no-interaction
poetry run pytest tests/ -q                       # full suite
poetry run pytest tests/test_config.py -q         # single file
poetry run pytest tests/test_config.py::test_name # single test
poetry run ruff check .                            # lint
poetry run ruff format .                           # format (line-length 120)
poetry run cfn-lint ../deployment/infrastructure/*.yaml

# Go — test, build (from source/go/)
go test ./... -count=1                             # all Go tests
go test ./internal/config/ -run TestName -v        # single Go test
make all                                           # cross-compile all platforms → bin/
make macos-arm64 / linux-x64 / windows             # single target

# CLI usage (from source/)
poetry run ccwb init        # config wizard → config.yaml
poetry run ccwb deploy      # deploy CloudFormation stacks
poetry run ccwb package     # build binary + config.json
poetry run ccwb distribute  # distribute installer packages
poetry run ccwb test        # validate a deployment
poetry run ccwb cowork generate   # MDM config for Claude Desktop

# pre-commit (yamllint, cfn-lint, ruff, CFN validate, smoke tests)
pre-commit run --all-files
```

## Testing & CI
- Run `poetry run pytest tests/ -q` from `source/` before pushing.
- CI matrix: **Linux, macOS, AND Windows** — Windows tests are **blocking** (see `.claude/rules/windows-platform-guards.md`).
- Python 3.10/3.11/3.12 on Linux; 3.12 spot-check on macOS/Windows.
- Go tests run separately (`go-tests.yml`); CFN templates validated by `cfn-lint` + `cfn_nag`.
- A `cross-platform-lint` CI job flags `SO_REUSEADDR` without platform guards, `os.rename`, and `open()` without `encoding=` on changed Python files.
- **Every bug fix needs a regression test** that would have caught it.

## Critical Invariants (full detail in `.claude/rules/`)
- **Go ↔ Python config parity** — adding a field to Python `Profile` requires the matching field + JSON tag in Go `ProfileConfig`, and identical session-name logic. See `config-sync.md`, `credential-helper-parity.md`.
- **No boto3 inside credential-process** — it's called by the SDK; use direct HTTPS to avoid infinite recursion. See `credential-recursion.md`.
- **IAM actions use `bedrock:` namespace** — `bedrock-runtime:` does not exist. See `iam-actions.md`.
- **Quota requires OIDC** — skip quota for `auth_type in ("idc", "none")`. See `quota-requires-oidc.md`.
- **Use `profile.effective_auth_type`** — never assume `auth_type` exists on old configs. See `auth-type-compat.md`.
- **OTEL attribution chain** — `x-user-email` must always be present; never emit empty headers when a cached token exists. See `otel-attribution-chain.md`.
- CFN: no hardcoded names (`!Sub '${AWS::StackName}-*'`); provider-specific issuer URL formats; region-specific ELB account IDs. See `cfn-naming.md`, `issuer-url-format.md`, `region-availability.md`.

## Branch Strategy
- **Target branch: `beta`** (not `main`). `main` is release-only.
- Rebase onto latest `upstream/beta` before opening a PR.
- One concern per PR, ≤~300 lines, start the description with "Why". See `.claude/rules/pr-standards.md`, `branch-strategy.md`.
