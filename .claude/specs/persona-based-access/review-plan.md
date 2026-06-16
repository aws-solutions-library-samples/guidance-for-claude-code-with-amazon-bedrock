# Review Plan — Persona-Based Access Control

> Lead's partition of the changed surface into 4 disjoint review scopes for parallel adversarial review.
> Each reviewer owns ONE `review-<scope>.md` (PASS/FAIL). Lead consolidates: any FAIL ⇒ group FAILs.
> Dispatch the moment #25 (full Python+Go suite) goes green.

## Scope 1 — `review-python-cli.md` (reviewer: review-1)
The Python CLI + config + renderers (Tier 1: config.py, deploy.py).
- `source/claude_code_with_bedrock/config.py` (Profile fields + effective_auth_type)
- `source/claude_code_with_bedrock/cli/commands/deploy.py` (persona/budgets orchestration, Cognito skip, OIDC import guard, PERSONA_ORDER compute, role_arn write-back)
- `source/claude_code_with_bedrock/cli/commands/init.py` (wizard) — **NOTE: ~14 E501 are PRE-EXISTING (14 at HEAD = 14 now), not PBAC; do not FAIL on them** (decisions.md)
- `source/claude_code_with_bedrock/cli/commands/package.py` (_create_config persona serialization)
- `source/claude_code_with_bedrock/persona_template.py`, `budgets_template.py`, `persona_resolution.py`, `persona_validation.py`, `persona_defaults.py`
**Focus:** §4.1 schema correctness, effective_auth_type backward-compat, deploy ordering + stack-output guards (stack-ordering.md), CFN-naming in rendered output, the **3-ARN-shape Deny** in persona_template (R-highest), quota-requires-oidc gating.

## Scope 2 — `review-go-helper.md` (reviewer: review-2)
The Go credential helper + otel (Tier 1: credential-process/main.go, internal/config).
- `source/go/cmd/credential-process/main.go` + `main_test.go` (persona→role selection, selectRoleARN)
- `source/go/cmd/otel-helper/main.go` (persona wiring into the binary — **in scope though not in a task's file list**)
- `source/go/internal/config/config.go` + `personas_test.go` (PersonaConfig, §4.2 parity)
- `source/go/internal/jwt/decode.go` + `decode_test.go` (GetStringSlice)
- `source/go/internal/persona/` (resolve.go + test — the §4.3 resolver)
- `source/go/internal/otel/extract.go`, `headers.go`, `cache.go`, `persona_header_test.go`
- `source/go/go.sum`
**Focus:** Go↔Python parity (§4.2 tags, §4.3 logic — credential-helper-parity.md), **buildSessionName UNCHANGED** (parity tests green), no boto3/SDK-credential recursion in credential-process (credential-recursion.md), empty-personas backward-compat (uses FederatedRoleARN), x-user-email always present + x-persona empty-excluded (otel-attribution-chain.md), cache schema bump, cold-start (no heavy deps).

## Scope 3 — `review-infra-lambda.md` (reviewer: review-3)
CloudFormation templates + Lambda enforcement (Tier 1/2).
- `deployment/infrastructure/lambda-functions/quota_check/index.py`, `quota_monitor/index.py` (PERSONA_ORDER declared-order; **legacy most-restrictive preserved when unset** — verify byte-for-byte)
- `deployment/infrastructure/quota-monitoring.yaml` (PersonaOrder param → PERSONA_ORDER env on both Lambdas)
- `deployment/infrastructure/otel-collector.yaml` (#26 — x-persona→persona in BOTH from_context blocks + [[persona,OTelLib]] dimension)
- `deployment/infrastructure/bedrock-personas-dashboard.yaml`, `logs-insights-queries.yaml`
- `deployment/infrastructure/bedrock-personas.example.yaml` (committed CI fixture — the bypass-guard exemplar)
**Focus:** D3 PBAC-mode gating doesn't regress legacy quota; the otel-collector dimension actually closes the empty-dashboard gap (#26); cfn-lint clean vs HEAD baseline; cfn-naming (no hardcoded names in NEW resources); Budgets SNS confused-deputy guard; partition/region awareness; **the example fixture's Deny covers all 3 ARN shapes**.

## Scope 4 — `review-tests-parity.md` (reviewer: review-4)
The test suite + cross-impl parity + docs.
- `source/tests/test_persona_*.py`, `test_backward_compat_personas.py`, `test_lambda_persona_order.py`, `test_deploy_personas.py`, `test_init_personas.py`, `test_package_personas.py`, `test_budgets_template.py`, `test_config.py`
- `source/tests/fixtures/persona_resolution_cases.json`
- `source/tests/test_persona_parity.py` (the Go↔Python oracle)
- `assets/docs/QUOTA_MONITORING.md`, `.gitignore`
**Focus:** Does the parity test genuinely cross-check Go vs Python (not just self-consistent)? Does the bypass-guard test FAIL if a Deny ARN shape is removed (it must)? Backward-compat coverage real? Tests assert behavior, not just "runs"? Every bug-fix-class change has a regression test (CLAUDE.md)? No silent CI skips when Go absent (must fail, not skip).

## Cross-scope seams (reviewers SendMessage each other; lead arbitrates)
- §4.2/§4.3 contract spans Scope 1 (Python) ↔ Scope 2 (Go) ↔ Scope 4 (parity test).
- PERSONA_ORDER spans Scope 1 (deploy.py compute) ↔ Scope 3 (yaml param + lambda consume).
- x-persona spans Scope 2 (otel-helper emit) ↔ Scope 3 (collector dimension) ↔ Scope 3 (dashboard consume).

## Pre-existing-debt allowlist (do NOT FAIL on these)
- init.py 14×E501 (pre-existing, verified 14@HEAD).
- quota-monitoring.yaml 3×W3002 (pre-existing Code-path packaging warnings).
- __pycache__/ dirs untracked (build noise; gitignore/commit-stage concern, not review).
