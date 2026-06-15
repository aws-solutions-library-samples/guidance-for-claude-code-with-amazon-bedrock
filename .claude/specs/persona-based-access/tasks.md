# Tasks — Persona-Based Access Control & Cost Governance

> Parallel groups; tasks within a group are file-disjoint and run concurrently. Groups are barriers.
> Roles: `[coding]` (Python + Go), `[devops]` (CFN/Lambda wiring/templates). Verification command per task.
> Contracts frozen in `spec.md` §4. All commands run from `source/` (Python) or `source/go/` (Go) unless noted.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

---

## Group 1: Foundation contracts (front-loaded — unblocks everything)
Spec ref: `spec.md#4` data contracts. Small, fast, disjoint. Everything downstream depends on these landing first.

- [ ] [coding] Add persona fields + `effective_auth_type` to Python `Profile` | `source/claude_code_with_bedrock/config.py` | `personas: list[dict]=field(default_factory=list)`, `groups_claim_name: str="groups"`, `fallback_persona: str|None=None` added; `effective_auth_type` property returns "oidc" when `sso_enabled` truthy else "none" (honor future `auth_type` attr if present); `from_dict` preserves persona fields; old profiles load with `personas=[]`. Run: `poetry run pytest tests/test_config.py -q && poetry run ruff check claude_code_with_bedrock/config.py`
- [ ] [coding] Add `PersonaConfig` + persona fields to Go `ProfileConfig` | `source/go/internal/config/config.go` | `PersonaConfig` struct exactly per spec §4.2; `Personas []PersonaConfig`, `GroupsClaimName string`, `FallbackPersona string` all `json:"...,omitempty"`; empty slice round-trips; existing fields untouched. Run: `cd source/go && go build ./... && go test ./internal/config/ -count=1`
- [ ] [coding] Add `Claims.GetStringSlice` to Go JWT decoder | `source/go/internal/jwt/decode.go` | new method handles `[]interface{}`→`[]string`, scalar `string`→1-elem slice, missing→nil; stdlib only; existing `GetString`/`GetFloat` untouched. Run: `cd source/go && go test ./internal/jwt/ -count=1`
- [ ] [coding] Author shared persona-resolution fixtures | `source/tests/fixtures/persona_resolution_cases.json` | JSON array of cases `{groups, personas(ordered), fallback, expected_name|null}` covering: single match, no-match+no-fallback→null, no-match+fallback, multi-match→first declared, empty personas→null. `[skip-verify]` (data file). Run: `python -c "import json;json.load(open('tests/fixtures/persona_resolution_cases.json'))"`

> Done when: Python+Go configs carry persona fields (parity), JWT slice accessor exists, fixtures committed. Barrier before Group 2.

---

## Group 2: Resolvers + renderers + JWT wiring (wide parallel)
Spec ref: `spec.md#4.3`, `design.md#2.2`. All file-disjoint; consume Group 1 contracts.

- [ ] [coding] Python shared persona resolver | `source/claude_code_with_bedrock/persona_resolution.py` | `resolve_persona(user_groups, personas_ordered, fallback)` per spec §4.3 (declared-order, fallback, None); pure fn; passes all Group-1 fixtures. Run: `poetry run pytest tests/test_persona_resolution.py -q`
- [ ] [coding] Go persona resolver | `source/go/internal/persona/resolve.go` + `resolve_test.go` | `Resolve(groups, personas, fallback)` per §4.3; table tests incl. all fixture cases; declared-order precedence. Run: `cd source/go && go test ./internal/persona/ -count=1`
- [ ] [coding] Persona CFN renderer | `source/claude_code_with_bedrock/persona_template.py` | `render_personas_stack(...)` emits valid CFN: per-persona Role (groups trust cond `ForAnyValue:StringEquals <issuer>:groups`), ManagedPolicy with Allow + **Deny across foundation-model/* , inference-profile/* , application-inference-profile/* **, permission boundary for restricted, `${AWS::Partition}`, `aws:RequestedRegion`, namespaced PutMetricData, `Output {Name}RoleArn`; pure fn. Run: `poetry run pytest tests/test_persona_template.py -q`
- [ ] [coding] Budgets CFN renderer | `source/claude_code_with_bedrock/budgets_template.py` | `render_budgets_stack(...)` emits per-persona (cost-tag CostFilter) + account `AWS::Budgets::Budget`, 50/80/100% actual+forecast → `${AWS::StackName}-budget-alerts` topic w/ `aws:SourceAccount` TopicPolicy. Run: `poetry run pytest tests/test_budgets_template.py -q`
- [ ] [coding] Wire persona→role selection in credential-process | `source/go/cmd/credential-process/main.go` | in `getAWSCredentials`, direct mode + non-empty Personas → resolve via `persona.Resolve(claims.GetStringSlice(groupsClaim), ...)` and assume `persona.RoleARN`; no-match+no-fallback → clear non-zero error; empty personas → unchanged `FederatedRoleARN`; all 3 call sites covered; no boto3. Run: `cd source/go && go test ./cmd/credential-process/ -count=1 && go build ./...`
- [ ] [coding] Persona validation helper | `source/claude_code_with_bedrock/persona_validation.py` | `validate_personas(personas, fallback)` → list of errors: dup names, empty/`group` missing, bad `enforcement_mode`, fallback not a persona, model glob sanity. Run: `poetry run pytest tests/test_persona_validation.py -q`

> Done when: both resolvers pass shared fixtures (parity), renderers produce lint-clean YAML, helper assumes persona role. Barrier before Group 3.

---

## Group 3: Integration — deploy, package, init, otel, lambdas, templates (wide parallel)
Spec ref: `design.md#2.3–2.8`. Disjoint files; consume Group 2 modules.

- [ ] [coding] otel-helper persona header | `source/go/internal/otel/extract.go`, `source/go/internal/otel/headers.go`, `source/go/internal/otel/cache.go` | add `Persona` to `UserInfo`, `"persona":"x-persona"` to `HeaderMapping`, populate via `persona.Resolve` from claims+config; empty → no header (FormatHeaders exclusion); bump `currentCacheSchemaVersion`. Run: `cd source/go && go test ./internal/otel/ -count=1`
- [ ] [coding] deploy.py persona+budgets orchestration | `source/claude_code_with_bedrock/cli/commands/deploy.py` | add `persona`/`budgets` stack types; `_deploy_persona_stack`: FederationType pre-check (skip+warn on cognito), import OIDCProviderArn (fail clear if absent), render→build dir (utf-8)→deploy, seed GROUP quota policy per persona (reuse `QuotaPolicyManager`), create tagged inference profiles (idempotent check-then-create), deploy budgets + persona dashboard; gate on `effective_auth_type=="oidc"` + non-empty personas. Run: `poetry run pytest tests/test_deploy_personas.py -q && poetry run ruff check claude_code_with_bedrock/cli/commands/deploy.py`
- [ ] [coding] package.py persona serialization | `source/claude_code_with_bedrock/cli/commands/package.py` | `_create_config` emits `personas[]` (with resolved `role_arn` from stack outputs), `groups_claim_name`, `fallback_persona`; only when personas configured; encoding utf-8. Run: `poetry run pytest tests/test_package_personas.py -q`
- [ ] [coding] init.py persona wizard | `source/claude_code_with_bedrock/cli/commands/init.py` | after quota section, SSO+quota-gated questionary loop collects personas + `groups_claim_name` + `fallback_persona`; `wizard_fields` includes them in `_save_configuration`. Run: `poetry run pytest tests/test_init_personas.py -q`
- [ ] [devops] Lambda declared-order resolution (PBAC mode) | `deployment/infrastructure/lambda-functions/quota_check/index.py`, `deployment/infrastructure/lambda-functions/quota_monitor/index.py` | gated on new `PERSONA_ORDER` env var: first-declared-group wins; unset → legacy most-restrictive `min()` preserved; `extract_groups_from_claims` unchanged. Run: `poetry run pytest ../deployment/infrastructure/lambda-functions/ -q` (or module-local unittest)
- [ ] [devops] quota-monitoring.yaml PERSONA_ORDER wiring | `deployment/infrastructure/quota-monitoring.yaml` | add `PERSONA_ORDER` env var (empty default) to quota_check + quota_monitor functions; cfn-lint clean. Run: `cd .. && poetry run cfn-lint deployment/infrastructure/quota-monitoring.yaml`
- [ ] [devops] Persona dashboard + Logs Insights queries | `deployment/infrastructure/bedrock-personas-dashboard.yaml`, `deployment/infrastructure/logs-insights-queries.yaml` | separate dashboard (cfn-naming compliant) with per-persona token/spend/Allow-Deny widgets + top-user leaderboard (group by `persona`); append per-persona QueryDefinitions. Run: `cd .. && poetry run cfn-lint deployment/infrastructure/bedrock-personas-dashboard.yaml deployment/infrastructure/logs-insights-queries.yaml`
- [ ] [devops] Committed persona stack fixture for CI | `deployment/infrastructure/bedrock-personas.example.yaml` | rendered from the 2 reference personas (eng+sales); the bypass-proof Deny on all 3 ARN shapes visible; cfn-lint + cfn_nag clean. Run: `cd .. && poetry run cfn-lint deployment/infrastructure/bedrock-personas.example.yaml`
- [ ] [coding] Register reference personas in init defaults + sample config | `source/claude_code_with_bedrock/cli/commands/init.py` is OWNED by the wizard task above — instead put seed data in `source/claude_code_with_bedrock/persona_defaults.py` | `REFERENCE_PERSONAS` constant (engineering, sales) per design §3 importable by wizard + tests. Run: `poetry run pytest tests/test_persona_defaults.py -q`

> Done when: deploy renders+deploys persona/budgets/dashboard, package serializes personas, wizard collects them, otel emits x-persona, lambdas honor declared order, fixtures lint clean. Barrier before Group 4.

---

## Group 4: End-to-end validation + cross-impl parity
Spec ref: `spec.md#4.3` parity, FR-9.4. Depends on Groups 2–3.

- [ ] [coding] Go↔Python persona-resolution parity test | `source/tests/test_persona_parity.py` | drive Go resolver (via compiled binary or `go run` harness) and Python resolver over the SAME Group-1 fixtures; assert identical persona names; include the buildSessionName-unchanged assertion. Run: `poetry run pytest tests/test_persona_parity.py -q`
- [ ] [coding] Backward-compat regression | `source/tests/test_backward_compat_personas.py` | pre-persona profile/config.json loads; `personas==[]`; helper path uses `FederatedRoleARN`; legacy multi-group quota = most-restrictive (PERSONA_ORDER unset). Run: `poetry run pytest tests/test_backward_compat_personas.py -q`
- [ ] [coding] Inference-profile bypass guard test (R-highest) | `source/tests/test_persona_policy_bypass.py` | assert rendered sales policy Denies `inference-profile/*sonnet*` and `application-inference-profile/*` and `foundation-model/*sonnet*` (all 3); a foundation-model-only Deny must fail the test. Run: `poetry run pytest tests/test_persona_policy_bypass.py -q`
- [ ] [coding] Full Python suite + Go suite green | (no new files; runs existing) | `[skip-format-check]` aggregate gate. Run: `poetry run pytest tests/ -q && cd go && go test ./... -count=1`

> Done when: parity holds, backward-compat proven, bypass impossible, both suites green. Barrier before review.

---

## Group 5: Documentation (FR-10) — after review PASS
Spec ref: FR-10. Authored via `documentation` skill in Phase 4 (lead-coordinated).

- [ ] [devops] PBAC_README.md | `PBAC_README.md` (repo root) | covers FR-10.2 (a)-(m): overview, config schema, per-IdP groups setup, deploy flow + stack ordering + Cognito skip, the inference-profile Deny invariant as a prominent ⚠️, enforcement (OTEL+quota reuse), cost attribution, budgets+SNS, dashboards, dynamic admin + rollback, no-match/fallback, auth-type/Cognito limits, troubleshooting. Reflects ACTUAL behavior. Run: `npx --yes markdownlint-cli2 PBAC_README.md || true` (lint advisory)
- [ ] [devops] Link PBAC_README from main README | `README.md` | features/docs section links to `PBAC_README.md`. Run: `grep -q "PBAC_README.md" README.md`

---

## Notes
- **No two tasks in a group write the same file** — verified: Group 3's wizard task owns `init.py`; persona defaults live in a separate `persona_defaults.py`.
- Lambda resolver duplication (separate deploy artifact) is intentional (design §5); parity test covers drift.
- Worktrees not needed — task graph is fully file-disjoint.
- Review scopes (Phase 2 step 12): `python-cli` (config/deploy/package/init/renderers), `go-helper` (credential-process/otel/persona/jwt/config), `infra-lambda` (CFN templates + lambdas), `tests-parity` (all test files). 4 reviewers, one each.
