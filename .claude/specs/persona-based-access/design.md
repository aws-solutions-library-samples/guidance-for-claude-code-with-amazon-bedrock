# Design — Persona-Based Access Control & Cost Governance

> Companion to `spec.md`. Architecture, component design, file-by-file build plan, and the deploy/runtime flows. Line refs are from the research sweeps (2026-06-15) — treat as starting points, re-confirm before editing.
>
> **Status: IMPLEMENTED (2026-06-16).** This is the pre-build design/blueprint. It is broadly as-built, with the deltas in `spec.md §0` (Implementation amendments). The authoritative as-built reference is **`PBAC_README.md`** + **`decisions.md`**. Notable design-vs-shipped deltas: the persona dashboard deploys **inline** within the persona flow (not a separate scheduled stack); the bypass guard is the pytest `test_persona_policy_bypass.py` (not a `ccwb test` assertion); generic-OIDC issuer-host uses `oidc_issuer_url`; `effective_auth_type` has no `auth_type` passthrough; per-persona alerting uses a stored `USER#<email>/GROUPS` record; persona serialization is gated on direct federation. Some predicted filenames/line-refs below differ from what shipped (e.g. `test_config_personas.py` shipped as additions to `test_config.py`); trust the repo over this file.

## 1. Architecture (end-to-end)

```
config.yaml (personas[], groups_claim_name, fallback_persona, budgets)
   │  ccwb init  (wizard writes persona block)
   ▼
Profile (config.py)  ──asdict──▶  ~/.ccwb/profiles/<name>.json
   │                                          │ ccwb package (_create_config allowlist + persona role_arns)
   │ ccwb deploy                               ▼
   │   1. auth stack  (existing, exports OIDCProviderArn, FederationType)
   │   2. quota stack (existing; QuotaPolicies/UserQuotaMetrics/QuotaCheckApi)
   │   3. RENDER bedrock-personas.yaml from personas[]  ◀── new (PersonaTemplateRenderer)
   │      deploy it: imports OIDCProviderArn; N× {Role+Policy+Boundary}; outputs {Name}RoleArn
   │   4. seed GROUP quota policy per persona (QuotaPolicyManager, reuse)
   │   5. create tagged Application Inference Profiles per persona (+ cost-alloc tags)
   │   6. RENDER/deploy bedrock-budgets.yaml: per-persona + account Budgets → budget-alerts SNS
   │   7. deploy bedrock-personas-dashboard.yaml (separate dashboard) + persona Logs Insights queries
   ▼                                          config.json (with per-persona role_arn)
Go credential-process (single package)         │
   load config → OIDC auth → parse `groups` ───┤
   resolve_persona(groups, personas, fallback) │   ← §4.3 algorithm
   AssumeRoleWithWebIdentity(persona.RoleARN)  │   ← was: cfg.FederatedRoleARN
   (quota-check API call unchanged)            │
Go otel-helper                                 │
   resolve_persona(...) → emit x-persona ──────┘ → collector → metric label `persona`
quota_check / quota_monitor Lambdas
   resolve by PERSONA_ORDER (declared) in PBAC mode, else legacy most-restrictive
```

## 2. Components & files

### 2.1 Python — config & schema (Tier 1)
- **`config.py`**: add `personas: list[dict]`, `groups_claim_name: str = "groups"`, `fallback_persona: str | None`, `account_budget_amount_usd: float | None`, and the `effective_auth_type` property (`"oidc" if sso_enabled else "none"` — no `auth_type` passthrough as shipped, §0 A1). `from_dict` field-filter auto-preserves; `default_factory=list` gives backward-compat. `validate_personas()` ships in its own `persona_validation.py` (unique names, non-empty `group`, valid `enforcement_mode`, string model globs, fallback names an existing persona).
- **`models.py`**: no new `PolicyType` (D6). If a `Persona` value object helps the renderer, add a frozen dataclass `PersonaDefinition` with `.from_dict()` for internal use — but `Profile.personas` stays `list[dict]` on disk (D9).

### 2.2 Python — persona template renderer (new module, the heart of D1)
- **New `source/claude_code_with_bedrock/persona_template.py`**: `render_personas_stack(personas: list[dict], groups_claim_name, issuer_host, partition_aware=True) -> str` returns CFN YAML. Per persona emits: `AWS::IAM::Role` (trust = `sts:AssumeRoleWithWebIdentity` + `sts:TagSession`, Condition `ForAnyValue:StringEquals {<issuer_host>:groups: [<group>]}`), `AWS::IAM::ManagedPolicy` (Allow permitted + **Deny excluded across all 3 ARN shapes** + List + namespaced PutMetricData), `AWS::IAM::ManagedPolicy` permission boundary for restricted personas, and an `Output {Name}RoleArn`. Uses `${AWS::Partition}`, `aws:RequestedRegion` ∈ regions param. Pure function (no IO) → unit-testable.
- **New `source/claude_code_with_bedrock/budgets_template.py`**: `render_budgets_stack(personas, account_budget, topic_logical) -> str` → `AWS::Budgets::Budget` per persona (CostFilter on the persona cost-allocation tag) + account total, 50/80/100% actual + forecast, all → `${AWS::StackName}-budget-alerts` topic with the confused-deputy `aws:SourceAccount` TopicPolicy.

### 2.3 Python — deploy orchestration (Tier 1)
- **`deploy.py`**: add `"persona"` + `"budgets"` stack types. New `_deploy_persona_stack`: (a) read `${AuthStack}-FederationType` → if `cognito`, **skip + warn** (D5); (b) read `${AuthStack}-OIDCProviderArn`, fail clearly if absent (`stack-ordering.md`); (c) render YAML to a build dir (utf-8), `cfn-lint` it in-process if available; (d) deploy via `CloudFormationManager`; (e) seed GROUP quota policies via `QuotaPolicyManager`; (f) create inference profiles (boto3 `bedrock.create_inference_profile`, idempotent — check-then-create); (g) deploy budgets stack; (h) deploy persona dashboard + queries. Gate the whole block on `effective_auth_type == "oidc"` and non-empty `personas`.

### 2.4 Python — package (Tier 2)
- **`package.py` `_create_config`**: after quota block, add persona serialization — read each persona's role ARN from the persona stack outputs (or from `profile` if deploy stored them) and emit the §4.2 `personas` array + `groups_claim_name` + `fallback_persona`.

### 2.5 Python — init wizard (Tier 2)
- **`init.py`**: after the quota section (~line 1157), gated on SSO+quota, add a `questionary` loop to define personas (name, group, model globs, limits, budget, tags) + top-level `groups_claim_name` + `fallback_persona`. Add `"personas"` etc. to `wizard_fields` in `_save_configuration` (~line 2087).

### 2.6 Go — helper (Tier 1)
- **`internal/config/config.go`**: add `Personas []PersonaConfig`, `GroupsClaimName`, `FallbackPersona` (+ `PersonaConfig` type, §4.2), all `omitempty`.
- **`internal/jwt/decode.go`**: add `Claims.GetStringSlice(key) []string` (handles `[]interface{}` and scalar). Stdlib only.
- **New `internal/persona/resolve.go`**: `Resolve(groups []string, personas []config.PersonaConfig, fallback string) (*config.PersonaConfig, error)` implementing §4.3 declared-order + fallback. Pure, table-tested.
- **`cmd/credential-process/main.go` `getAWSCredentials` (~line 550)**: when `FederationType=="direct"` and `len(Personas)>0`, resolve persona from `auth.TokenClaims.GetStringSlice(cfg.groupsClaimName())` and pass `persona.RoleARN`; on no-match+no-fallback, return a clear error. Empty personas → unchanged `FederatedRoleARN`. Covers all 3 call sites (silent refresh, refresh-token, full auth).
- **`internal/otel/extract.go` + `headers.go`**: add `Persona` to `UserInfo`, `"persona":"x-persona"` to `HeaderMapping`; otel-helper populates it via `persona.Resolve(...)` using the same config+claims. Bump `currentCacheSchemaVersion` in `cache.go`.
- **`buildSessionName` (sts.go) — DO NOT TOUCH**; existing parity tests must stay green.

### 2.7 Lambdas — enforcement + alerting (Tier 1/2)
- **`quota_check/index.py`** + **`quota_monitor/index.py`**: add declared-order resolution gated on a new `PERSONA_ORDER` env var (comma-separated persona group values in declared order). When set, `resolve_quota_for_user`/`resolve_user_quota` pick the **first** matching group's policy; when unset, legacy most-restrictive `min()` is preserved (D3). `extract_groups_from_claims` unchanged (still returns a set; ordering comes from `PERSONA_ORDER`). `quota-monitoring.yaml` gains the `PERSONA_ORDER` env var on both functions (empty default).
- **As-built (L5, per-persona alerting):** `quota_check` also persists `store_user_groups(email, groups)` → `USER#<email>/GROUPS` (TTL 90d, distinct `sk` so it's outside the `MONTH#` usage scan; best-effort, never blocks the check). `quota_monitor` — which has no JWT — calls `get_user_groups(email)` to feed `resolve_user_quota`, so its declared-order branch is live for alert thresholds (previously always defaulted). `quota-monitoring.yaml` `QuotaCheckRole` gains scoped `dynamodb:PutItem` on `UserQuotaMetrics`.

### 2.8 Infra templates (new, auth-template tier)
- Renderer **outputs** (not committed as static), but commit a **fixture** `deployment/infrastructure/bedrock-personas.example.yaml` (rendered from the 2 reference personas) for CI `cfn-lint` + human review.
- **`bedrock-personas-dashboard.yaml`** (separate dashboard, `cfn-naming` compliant) + persona blocks appended to **`logs-insights-queries.yaml`**.
- `quota-monitoring.yaml`: add `PERSONA_ORDER` env var wiring.

## 3. Reference personas (seed `config.yaml` + docs)
- **engineering**: group `eng-team`, allowed `["anthropic.*"]`, denied `[]`, monthly 300M, block, tags `{Team: Engineering}`.
- **sales**: group `sales-team`, allowed `["anthropic.*haiku*"]`, denied `["anthropic.*sonnet*","anthropic.*opus*"]` (all 3 ARN shapes), monthly 10M, block, permission boundary, tags `{Team: Sales}`.

## 4. Testing strategy (maps to FR-9.4 + NFR-1) — as shipped
- **Python unit**: renderer output, `validate_personas`, `effective_auth_type` (oidc/none + legacy `sso_enabled`-only; the `auth_type`-in-config-is-filtered case per §0 A1), `_create_config` persona serialization (incl. the Cognito-gated negative case, A6), issuer-host per IdP incl. the **generic→`oidc_issuer_url`** regression (A2), validation-fails-deploy (A3), declared-order vs legacy resolution in both Lambdas, and the L5 `store_user_groups`/`get_user_groups` round-trip.
- **Go unit**: `persona.Resolve` table tests (no-match/fallback/multi-match declared-order/empty), `GetStringSlice` (array+scalar+missing), `config` round-trip, otel `x-persona` empty-exclusion, **existing `buildSessionName` tests unchanged**.
- **Parity**: shared JSON fixtures of (groups, personas) → identical persona name from Go `Resolve` and Python resolver (`test_persona_parity.py`, fails-not-skips when Go absent).
- **CFN**: `cfn-lint` the committed `bedrock-personas.example.yaml` + dashboard/queries/otel-collector/quota-monitoring (clean vs HEAD baseline).
- **Backward-compat**: a pre-persona `config.json`/profile loads, helper uses `FederatedRoleARN`, legacy quota path (`PERSONA_ORDER` unset → most-restrictive) unchanged.
- **The bypass test (R-highest)**: `tests/test_persona_policy_bypass.py` renders the `sales` persona and asserts the Deny covers sonnet+opus across all 3 ARN shapes — incl. a meta-test that a foundation-model-only Deny FAILS the check (teeth). (Not a `ccwb test`/simulate-custom-policy assertion as originally sketched.)

## 5. Repo layout (new files — AS SHIPPED)
```
source/claude_code_with_bedrock/
  persona_template.py            # persona CFN renderer
  budgets_template.py            # budgets CFN renderer
  persona_resolution.py          # shared Python resolver (§4.3)
  persona_validation.py          # validate_personas (called by wizard AND deploy, A3)
  persona_defaults.py            # REFERENCE_PERSONAS (engineering, sales)
source/go/internal/persona/resolve.go (+ resolve_test.go)   # Go resolver
deployment/infrastructure/
  bedrock-personas.example.yaml      # committed CI fixture (cfn-lint + bypass exemplar)
  bedrock-personas-dashboard.yaml    # persona CloudWatch dashboard
PBAC_README.md                       # FR-10 operator guide (repo root)
# New Python tests (source/tests/):
#   test_persona_template.py, test_persona_resolution.py, test_persona_validation.py,
#   test_budgets_template.py, test_deploy_personas.py, test_init_personas.py,
#   test_package_personas.py, test_persona_parity.py, test_persona_policy_bypass.py,
#   test_lambda_persona_order.py, test_backward_compat_personas.py,
#   fixtures/persona_resolution_cases.json
#   (config-persona tests live in the existing test_config.py, not a separate file)
# New Go tests: internal/config/personas_test.go, internal/otel/persona_header_test.go,
#   cmd/credential-process/main_test.go
# Modified (not new): config.py, cli/commands/{deploy,destroy,init,package}.py,
#   go/{cmd/credential-process,cmd/otel-helper,internal/config,internal/jwt,internal/otel},
#   deployment/infrastructure/{quota-monitoring.yaml, otel-collector.yaml,
#   logs-insights-queries.yaml, lambda-functions/quota_{check,monitor}/index.py},
#   source/otel_helper/otel-helper.sh (L4 schema-gate)
```
> Note: the Lambdas can't import from the `ccwb` package at runtime (separate deploy artifact). The shared resolver is duplicated as a small self-contained function in each Lambda **and** in `persona_resolution.py`; parity tests assert they agree. Keep it tiny (the §4.3 algorithm is ~10 lines).

## 6. Open design details — ALL RESOLVED (as shipped)
- DD-1 trust operator: ✅ `ForAnyValue:StringEquals` on `<issuer_host>:<groups_claim>` (persona_template.py); per-IdP `groups` emission + the issuer-host form documented in PBAC_README §3 (incl. the generic→`oidc_issuer_url` correction, A2).
- DD-3 CI lint: ✅ committed `bedrock-personas.example.yaml` fixture, cfn-lint-clean; renderer also unit-tested.
- DD-4 budgets: ✅ separate `budgets_template.py`; amounts from `budget_amount_usd` (per persona) + `account_budget_amount_usd` (top-level, wired through Profile+wizard); 50/80/100 actual + 100 forecast → dedicated `${AWS::StackName}-budget-alerts` topic with `aws:SourceAccount` guard.
- DD-5 AIP idempotency: ✅ check-then-create by name; teardown via `_delete_persona_inference_profiles` in `destroy`; deploy also warns on orphaned AIPs when a persona is removed (M2).
