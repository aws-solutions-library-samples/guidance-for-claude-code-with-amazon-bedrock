# Design — Persona-Based Access Control & Cost Governance

> Companion to `spec.md`. Architecture, component design, file-by-file build plan, and the deploy/runtime flows. Line refs are from the research sweeps (2026-06-15) — treat as starting points, re-confirm before editing.

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
- **`config.py`**: add `personas: list[dict]`, `groups_claim_name: str = "groups"`, `fallback_persona: str | None`, and `effective_auth_type` property. `from_dict` field-filter (line ~215) auto-preserves; `default_factory=list` gives backward-compat. Add a `validate_personas()` helper (unique names, non-empty `group`, valid `enforcement_mode`, fallback names an existing persona).
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

### 2.7 Lambdas — enforcement (Tier 1/2)
- **`quota_check/index.py`** + **`quota_monitor/index.py`**: add declared-order resolution gated on a new `PERSONA_ORDER` env var (comma-separated persona group values in declared order). When set, `resolve_quota_for_user`/`resolve_user_quota` pick the **first** matching group's policy; when unset, legacy most-restrictive `min()` is preserved (D3). `extract_groups_from_claims` unchanged (still returns a set; ordering comes from `PERSONA_ORDER`). `quota-monitoring.yaml` gains the `PERSONA_ORDER` env var on both functions (empty default).

### 2.8 Infra templates (new, auth-template tier)
- Renderer **outputs** (not committed as static), but commit a **fixture** `deployment/infrastructure/bedrock-personas.example.yaml` (rendered from the 2 reference personas) for CI `cfn-lint` + human review.
- **`bedrock-personas-dashboard.yaml`** (separate dashboard, `cfn-naming` compliant) + persona blocks appended to **`logs-insights-queries.yaml`**.
- `quota-monitoring.yaml`: add `PERSONA_ORDER` env var wiring.

## 3. Reference personas (seed `config.yaml` + docs)
- **engineering**: group `eng-team`, allowed `["anthropic.*"]`, denied `[]`, monthly 300M, block, tags `{Team: Engineering}`.
- **sales**: group `sales-team`, allowed `["anthropic.*haiku*"]`, denied `["anthropic.*sonnet*","anthropic.*opus*"]` (all 3 ARN shapes), monthly 10M, block, permission boundary, tags `{Team: Sales}`.

## 4. Testing strategy (maps to FR-9.4 + NFR-1)
- **Python unit**: renderer output (golden file), `validate_personas`, `effective_auth_type` (oidc/idc/none + legacy `sso_enabled`-only), `_create_config` persona serialization, declared-order vs legacy resolution in both Lambdas.
- **Go unit**: `persona.Resolve` table tests (no-match/fallback/multi-match declared-order/empty), `GetStringSlice` (array+scalar+missing), `config` round-trip, otel `x-persona` empty-exclusion, **existing `buildSessionName` tests unchanged**.
- **Parity**: shared JSON fixtures of (groups, personas) → identical persona name from Go `Resolve` and Python resolver.
- **CFN**: `cfn-lint` the committed example renders; `cfn_nag` clean.
- **Backward-compat**: a pre-persona `config.json`/profile loads, helper uses `FederatedRoleARN`, legacy quota path unchanged.
- **The bypass test (R-highest)**: simulate-custom-policy + assert Deny on a `inference-profile/us.anthropic.claude-sonnet-*` ARN for sales.

## 5. Repo layout (new files)
```
source/claude_code_with_bedrock/
  persona_template.py            # renderer (new)
  budgets_template.py            # renderer (new)
  persona_resolution.py          # shared Python resolver (new; used by lambdas-as-lib + tests)
source/go/internal/persona/resolve.go   # Go resolver (new)
deployment/infrastructure/
  bedrock-personas.example.yaml  # committed fixture for cfn-lint (new)
  bedrock-personas-dashboard.yaml# (new)
source/tests/test_persona_template.py, test_persona_resolution.py, test_config_personas.py (new)
source/go/internal/persona/resolve_test.go (new)
PBAC_README.md                   # (new, FR-10)
```
> Note: the Lambdas can't import from the `ccwb` package at runtime (separate deploy artifact). The shared resolver is duplicated as a small self-contained function in each Lambda **and** in `persona_resolution.py`; parity tests assert they agree. Keep it tiny (the §4.3 algorithm is ~10 lines).

## 6. Open design details (resolve during build, log in decisions.md)
- DD-1 trust operator: use `ForAnyValue:StringEquals` on `<issuer>:groups` (arrays); document per-IdP `groups` emission.
- DD-3 CI lint: committed `bedrock-personas.example.yaml` fixture (chosen over render-in-CI).
- DD-4 budgets: separate rendered template (`budgets_template.py`), amounts from config.
- DD-5 AIP idempotency: check-then-create by name; teardown in `destroy`.
