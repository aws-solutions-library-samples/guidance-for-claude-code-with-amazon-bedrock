# Spec — Persona-Based Access Control & Cost Governance

> Slug: `persona-based-access` · Branch: `rubab-dev1` · Status: **IMPLEMENTED + reviewed (build-phase 4 scopes PASS) + Low-issue wave + 2nd deep-dive (1 HIGH + 4 MED) + 3rd independent deep-dive (1 HIGH + 3 MED) + 3rd-pass LOW-wave (5 LOWs) + FR-5.1 install→use→teardown integration coverage + 4th independent deep-dive (2 MED + 1 parity LOW) + 4th-pass LOW-wave (L2 version-exact entitlement + L4 test-isolation) + bypass-suite converted presence→match at the source** as of 2026-06-16. Re-gate GREEN: Python 1227/0, Go 10 pkgs ok, go vet clean.
> Input: `requirements.md` (FR-1…FR-10). Research: three `code-explorer` sweeps (Python CLI, Go helper, CFN/Lambda) — findings folded in below.
>
> **This document is the pre-build design of record.** The decisions/contracts below were authored before implementation and are largely accurate, but a few details changed during build/review/fix. The authoritative as-built reference is **`PBAC_README.md`** (operator guide) + **`decisions.md`** (full chronological decision + fix log). Where this spec and the shipped code disagree, the code + `PBAC_README.md` win. See **§0 Implementation amendments** for the deltas.

## 0. Implementation amendments (what changed from the pre-build design)

Recorded post-build so this spec isn't misread as the final state. Each links to fuller detail in `decisions.md`.

- **A1 — `effective_auth_type` has NO `auth_type` passthrough (amends D2 / §4.1 / §4.3).** Shipped as `"oidc" if sso_enabled else "none"`, full stop. The "honors a future `auth_type`" branch was implemented then **removed** (L1, Low-wave): `auth_type` is not a `Profile` field and `from_dict` filters unknown keys, so the passthrough was dead code. If first-class IDC support is added later, make `auth_type` a real field then.
- **A2 — Generic-OIDC issuer-host derives from `oidc_issuer_url`, not `provider_domain` (amends §5 issuer rule).** The persona trust-condition issuer-host must equal the **registered** OIDC-provider URL: Auth0 keeps its trailing slash, Azure keeps `/v2.0`, Okta is the bare domain, and **generic/Teleport/Keycloak uses `oidc_issuer_url`** (often with a realm path). A review HIGH (issuer-host fix) corrected `_resolve_issuer_host`; getting this wrong silently hard-denies all users of that IdP.
- **A3 — Persona definitions are validated in the deploy path (new).** `validate_personas` now runs at the top of `_deploy_persona_stack` (not only in the wizard), so a hand-edited `config.yaml` with a bad `enforcement_mode`/`group` fails loudly instead of rendering silently-wrong infra (M1).
- **A4 — Persona dashboard is deployed INLINE within the persona flow** (a `{pool}-persona-dashboard` CFN stack created by `_deploy_persona_dashboard`, torn down explicitly by `destroy`), NOT as a separate scheduled DESTROYABLE_STACKS entry. `ccwb test` does NOT assert the bypass Deny — that guard shipped as the pytest `tests/test_persona_policy_bypass.py` (amends §7 risk row + §4.3 lambda note language).
- **A5 — Per-persona ALERTING is wired via a stored user→group record (amends §4.3 lambda behavior).** `quota_check` persists `USER#<email>/GROUPS` (TTL 90d) at issuance; `quota_monitor` (which has no JWT) reads it so its declared-order branch resolves persona alert thresholds — previously the monitor always fell to the default tier (L5). Enforcement (quota-check) and alerting (quota-monitor) now both honor per-persona limits.
- **A6 — Persona serialization into `config.json` is gated on `federation_type == "direct"`** (L3) — no dead persona data under Cognito federation.
- **A7 — Scope note:** built on `rubab-dev1` (not a `feat/persona-based-access` branch); §5/§6 branch language is aspirational. Personas serialize as `list[dict]` (D9 held).
- **A9 — Second independent deep-dive (2026-06-15, user-requested) — 1 HIGH, 4 MED fixed; see `decisions.md`.** A fresh skeptical review (5 parallel scopes + lead adjudication) over the whole `rubab-dev1` diff found issues the prior gates missed. Net changes folded into the as-built:
  - **HIGH — packaging without `--go` shipped a persona-blind binary.** The default `ccwb package` builds the legacy (PyInstaller/Nuitka) credential-process, which has **no** persona logic and always assumes the base `FederatedRoleARN`; persona serialization was gated on `federation_type=="direct"` but NOT on `use_go`. So an operator following the bare `ccwb package` in PBAC_README would silently ship a bundle where every restricted persona got the **broad base role** — a silent access-control bypass. Fix: `package.handle()` now hard-refuses (rc=1) via `_personas_require_go(profile, federation_type, use_go)` when a direct-federation persona profile is packaged without `--go`; `--regenerate-installers` warns. PBAC_README §4 + troubleshooting updated; 4 regression tests.
  - **MED — global cross-Region inference (CRIS) Allow gap.** The renderer gated all invoke Allows on `aws:RequestedRegion ∈ AllowedBedrockRegions`, but `global.anthropic.*` models send `aws:RequestedRegion="unspecified"` against the region-less FM ARN — so personas could not invoke any global model (the shipped `bedrock-auth-*.yaml` carry a second region-less `AllowBedrockInvokeGlobal` for exactly this). Fix: `persona_template.py` emits `AllowBedrockInvokeAllowedModelsGlobal` (region-less, scoped to allowed globs) on both the access policy and the boundary; the restricted Deny is also extended to the region-less shape so denied models stay denied on the global path. Example fixture regenerated (cfn-lint clean); bypass test extended with global-CRIS coverage + a renderer-mutation meta-test.
  - **MED — 80 compiled `.pyc` were tracked** (0 on `main`): `.gitignore`'s broad `!source/tests/**` re-include dragged caches back in. Fix: `git rm --cached` all 80 + re-exclude `source/tests/**/__pycache__/` and `*.pyc` after the negation.
  - **MED — test quality**: the deploy-scheduling test re-implemented the gate (tautology) → extracted `DeployCommand._should_schedule_personas` and the test now drives the real predicate; added a quota-monitor usage-scan regression proving the `USER#/GROUPS` record (sk=`GROUPS`) is excluded from the `MONTH#` usage scan (teeth-verified); pinned Go in `pytest-ci.yml` so the parity oracle's fail-not-skip is deterministic on all 3 OSes.
  - **Re-gate after fixes: Python 1178/0, Go 10 pkgs ok.** LOW items reported to the user for decision (not auto-fixed).
- **A10 — Third independent deep-dive (2026-06-15, user-requested) — 1 HIGH + 3 MED fixed; see `decisions.md`.** A fourth review pass (4 parallel skeptical agents + lead verification of every Tier-1 surface, each agent finding re-verified against code) found the FR-5.1 wrapper *install/teardown* surface — the most recently-added code — carried defects the AIP-routing build (A8) introduced but earlier passes hadn't probed:
>  - **HIGH — FR-5.1 launch wrapper was never installed.** `package._create_persona_model_wrapper` wrote `persona-model.sh`/`.ps1` into the dist dir, but neither `install.sh` nor `install.bat` copied them to `$HOME/claude-code-with-bedrock/` — the path PBAC_README §7 tells users to `source`. So per-persona model routing was silently inert via the documented install flow (access control via the IAM role was unaffected — routing/cost-attribution only). Fix: both installers now copy the wrapper (guarded on its presence) and print the source line; +installer-copy + `bash -n` regression tests.
>  - **MED — `--regenerate-installers` dropped the wrapper.** `_regenerate_installers` re-emitted config/installer/docs/settings but never re-ran `_create_persona_model_wrapper`, so a regenerated bundle advertised `inference_profile_arns` yet shipped no wrapper. Fix: regenerate now calls it; +regression test.
>  - **MED — wizard could save a config that fails `ccwb deploy`.** A budgeted persona with empty `cost_tags` passed `validate_personas` but `budgets_template._cost_filters_for_persona` raises → deploy aborts one command later. Fix: `validate_personas` now rejects `budget_amount_usd` without `cost_tags` (closes wizard AND hand-edit); +teethed test.
>  - **MED — destroy orphaned per-tier AIPs after entitlement shrank.** `_delete_persona_inference_profiles` derived AIP names from the persona's *current* `entitled_tiers`; if its models were narrowed post-deploy, the now-unentitled tier's AIP was never deleted. Fix: teardown now sweeps ALL tiers (haiku/sonnet/opus) + legacy name; +teethed real-method test (was previously only ever patched to a no-op).
>  - **Test hardening (user's regression-monitoring ask):** committed `bedrock-budgets.example.yaml` so CI cfn-lints the rendered Budgets stack (the persona stack already had this; budgets didn't) + drift guard; rewrote the tautological `test_unresolvable_tier_returns_none` into a real assertion. Two agent-claimed gaps were verified as FALSE POSITIVES (already covered): the otel `ExtractUserInfoWithPersona` Go tests and `jwt.GetStringSlice` scalar/non-string cases both exist.
>  - **Re-gate: Python 1207/0, Go 10 pkgs ok, cfn-lint clean (incl. new budgets fixture), zero new ruff.** LOW items reported to the user for decision (not auto-fixed).
>  - **Follow-on (2026-06-16, user-directed): all 5 LOWs fixed + FR-5.1 install→use→teardown integration coverage added.** L1 `tokenExpired` Go helper (exit-4 now tested), L2 PS1 wrapper PATH-resolves `claude` (anti-recursion via `-CommandType Application`), L3 init retry skips the opt-in confirm, L4 GROUPS write gated on `ENABLE_FINEGRAINED_QUOTAS` (the monitor only reads it then), L5 no budget for a zero-entitled-tier persona. New `tests/integration/test_persona_model_lifecycle.py` (+ Go `TestPersonaModelExportsFromConfigJSON`) drives package→use(real Go helper on the packaged config.json)→teardown and locks the invariant: AIP names created == ARNs serialized == ARNs routed == names destroyed (use-leg fails-not-skips without Go; teeth-verified). Re-gate **Python 1215/0, Go 10 pkgs ok, go vet clean, zero new ruff/E501**. Full record in `decisions.md` (2026-06-16 LOW-wave entry).
- **A11 — Fourth independent deep-dive (2026-06-16, user-requested) — 2 MED + 1 parity LOW fixed; docs realigned; see `decisions.md`.** A 6-scope adversarial pass (Go helper / deploy+destroy / package+init+config / CFN-IAM renderer / Lambda+budgets / docs-accuracy), every finding re-verified against code (incl. AWS service-authorization docs) before acting. The model-Deny core held under exhaustive bypass testing (0 bypasses). Net changes:
>  - **MED — global-CRIS Allow/Deny were INERT (amends A9).** The A9 "global-CRIS gap" fix added a region-less FM Allow/Deny but built the ARN as `foundation-model/anthropic.*<tier>*` (no leading `*`). Real global ids are `global.anthropic.…`, and IAM resource matching is anchored, so the glob never matched — the global Allow granted nothing and the global Deny guarded an unreachable path (both fail closed, so no bypass; but global models were silently unusable for every persona, defeating the supported config A9 set out to enable). Three prior passes missed it because the tests only asserted the ARN *string existed*, never that its glob *matched*. Fix: `_global_foundation_model_arns` now prepends `*` exactly as the inference-profile shapes do; new `test_global_cris_allow_glob_actually_matches_real_global_model_ids` models IAM's anchored match with `fnmatch` against real shipped global ids (teeth-verified; example fixture regenerated, cfn-lint clean).
>  - **MED — persona-dashboard orphan false-positive.** The inline persona-dashboard is never in `deploying_types`, so `_check_orphaned_stacks` flagged the live dashboard as "disabled in your configuration" and offered to delete it on **every** all-stacks re-deploy with personas configured. Fix: the dashboard is treated as managed-by-the-persona-flow — orphan-eligible only once the `persona` stack itself is no longer deploying (personas removed). New `TestOrphanedStackCheck` (2 cases: not-flagged-when-persona-deploying, flagged-when-persona-removed; teeth-verified). `_check_orphaned_stacks` previously had zero coverage.
>  - **LOW (parity) — Python `resolve_persona` scalar-groups divergence.** A scalar (non-list) `groups` claim made Python `set("eng-team")` iterate into characters and match nothing, while Go `jwt.GetStringSlice` normalizes a scalar to a single-element slice and matches. Unreachable today (no runtime caller of the Python resolver; the shared fixture types `groups` as a list), but it is the reference half of the §4.3 parity contract. Fix: wrap-not-iterate a `str`; +2 parity tests (scalar match + scalar non-substring-match).
>  - **Doc realignment:** PBAC_README §11 corrected (the quota Lambdas do **not** honor `fallback_persona` — fallback applies to the credential helper's *model access*, not the quota *tier*; unmatched users get the account default quota), §6 write-gate wording (`ENABLE_FINEGRAINED_QUOTAS` added), §3 generic-IdP registered-URL cell (redundant `https://` removed). README.md confirmed already-minimal (single discoverability link).
>  - **Reported LOWs (not auto-fixed, user decision):** (1) `bedrock:CallWithBearerToken` in the model-scoped Allow/Deny is inert (AWS requires `Resource:"*"` for it) — but **not a bypass** (bearer-token invocation also requires `bedrock:InvokeModel` on the model, which the Deny *does* block, and the persona's own `CallWithBearerToken` Allow is equally inert); pre-existing parity with `bedrock-auth-*.yaml`. (2) version-pinned deny globs can over-restrict an entitled tier's AIP (`entitled_tiers` probes version-lessly) — fails closed. (3) `install.bat` is written LF not CRLF (pre-existing, whole-installer, orthogonal to PBAC; cmd.exe tolerates LF — the PBAC `persona-model.ps1` IS correctly CRLF). (4) fallback-persona users get the default quota tier (now documented, §11).
>  - **Re-gate: Python 1220/0 (+5 over 1215: 1 global-CRIS glob-match, 2 orphan-check, 2 scalar-groups parity), Go 10 pkgs ok, go vet clean, cfn-lint clean, zero new ruff.**
>  - **Follow-on (2026-06-16, user-directed): L2 + L4 fixed + bypass-suite hardened to match-based.** **L2 (version-exact entitlement):** `entitled_tiers(persona, cris_prefix=…)` now probes a tier with its *resolved* CRIS model id (matched with the inference-profile shape), so a version-pinned deny on the tier's own model (e.g. `anthropic.claude-opus-4-7`) excludes that tier — deploy no longer creates an opus AIP sourced from a denied model (which would `AccessDenied` at runtime). Cross-tier data-residency fallback keeps the version-less probe (no muddying); budgets caller stays version-less; destroy still sweeps ALL tiers. +4 tests. **L4 (test isolation):** `test_destroy_skip_logic.py` now defaults `personas=[]` and mocks `_get_retained_resources` (the unmocked per-stack boto3 call) — the 9 tests drop from ~26s to ~0.4s (whole suite 84s→42s). **Bypass-suite audit (user-requested) — converted presence→match at the source:** assertion-by-assertion audit confirmed the R-highest guard's shape-coverage helper + inline checks were *presence/substring* (test #4 demonstrably PASSED throughout the global-CRIS bug — the proof). Per the user's "strengthen the helper itself" decision, rewrote the engine, not just added a parallel test: a single `_iam_glob_match` (fnmatch, IAM semantics) now backs a match-based `_shapes_covered_for_keyword` (converts #2 `test_deny_covers_all_three_shapes` + #3 `test_access_policy_deny_is_self_sufficient` at their root), a match-based #4 (global-CRIS region-less FM), a new positive Allow test (#5 only checked the negative), and `TestSalesDenyMatchesRealModelIds`. Each builds the realistic per-shape runtime ARN (FM=bare id, inference-profile=region/global-prefixed id) and asserts the rendered glob *matches* via fnmatch. Teeth-verified two ways: reverting the global-CRIS fix fails #4 + the new tests; disabling the inference-profile leading-`*` prepend fails #2/#3 (which the old substring helper passed). L1 (`CallWithBearerToken`) and L3 (`install.bat` LF) left as-is per user direction. **Re-gate: Python 1227/0 (+7), Go 10 pkgs ok, go vet clean, cfn-lint clean, zero new ruff.**
- **A8 — FR-5.1 per-persona model routing FULLY implemented (post-review, user-directed).** The original build only *tagged* AIPs for cost attribution; the ARN→routing half of FR-5.1 was deferred. Now fully built (full record: `fr5-model-routing.md`): (a) deploy creates **one AIP per entitled tier** (`{pool}-{persona}-{tier}`), `copyFrom` a **cross-Region (CRIS) inference profile** (not a single-region foundation model — required for multi-Region AIPs / CRIS routing), **partition-aware** (fixes the L-a GovCloud hardcode); (b) each AIP ARN is read back into `persona["inference_profile_arns"]` and serialized into `config.json` (new Go `PersonaConfig.InferenceProfileArns`, parity held); (c) new Go `credential-process --get-persona-model` resolves the persona from the cached token's groups claim and emits `ANTHROPIC_*_MODEL` exports; (d) `ccwb package` generates an **opt-in launch wrapper** (`persona-model.sh` + `persona-model.ps1`, CRLF) that applies those exports per-launch. Backward compatible: no personas / no ARNs / Cognito → no wrapper, static settings.json model unchanged. New module `persona_models.py` (tier entitlement + AIP naming/source, shared by deploy+destroy).

## 1. Summary

Layer **persona-based model-access control** and **per-persona cost governance** onto the existing `ccwb` system, reusing its quota subsystem rather than duplicating it. A persona = a named group (matched by the OIDC `groups` claim) with: an IAM role whose Bedrock policy enforces model Allow/Deny across all three ARN shapes, a GROUP-level quota policy for token limits, tagged inference profiles for cost attribution, and an AWS Budget. Personas are declared in `config.yaml`, materialized by a **CLI-rendered** dedicated CloudFormation stack, and resolved at credential-issuance time by the Go helper (single package, claim→role). Direct-IAM federation only in v1.

## 2. Key research findings that shape/correct the design

These came out of codebase exploration and **amend** assumptions in `requirements.md`:

- **F1 — No template rendering exists today.** All CFN is static `.yaml` + parameters, deployed via `CloudFormationManager.deploy_stack(template_path, params)`. FR-2.0's "CLI-rendered stack" is a *new pattern*: Python will generate `bedrock-personas.yaml` from `profile.personas` into a build dir, then deploy it through the existing manager. This is the chosen approach (CFN has no native iteration over N personas). **Decision D1.**
- **F2 — `effective_auth_type` does not exist.** The rule `auth-type-compat.md` cites it; code uses `getattr(profile, "sso_enabled", True)`. We will **add** the `effective_auth_type` property to `Profile` (maps `sso_enabled`→`"oidc"`/`"none"`; honors a future `auth_type`) to satisfy the rule and centralize the check. **Decision D2.**
- **F3 — Persona limits ARE existing GROUP quota policies.** `quota_check`/`quota_monitor` already resolve `POLICY#group#<value>` items. A persona's `group` value *is* the policy identifier — **no new `PolicyType`, no schema change.** We seed one GROUP policy per persona.
- **F4 — Multi-group resolution today is "most-restrictive-wins,"** not declared-order. FR-3.3 wants declared-order precedence. This is a **behavioral change to Tier-1 enforcement**, so it is **scoped to PBAC mode only**: when an ordered persona list is provided to the Lambdas (new env var `PERSONA_ORDER`), resolve by declared order; when absent (legacy/no personas), keep most-restrictive-wins untouched. **Decision D3.**
- **F5 — Persona telemetry dimension.** The dashboard/queries need a `persona` label on `claude_code.token.usage`. The resolved persona lives in credential-process, not the otel-helper. **Decision D4:** otel-helper independently resolves persona from the same `groups` claim + persona config it already loads (no cross-binary cache handshake), emitting `x-persona`. `FormatHeaders` already drops empties, so unmatched → no header (safe). Adds `Persona` to `UserInfo` + `"persona":"x-persona"` to `HeaderMapping`.
- **F6 — Google OIDC has no native `groups` claim** (its direct-IAM trust uses `accounts.google.com:aud`). Personas under Google require IdP-side custom group attributes. **Documented caveat**, not a code blocker.
- **F7 — Cognito mode has no OIDC-provider export** (`OIDCProviderArn` output is `Condition: UseDirectIAM`). Detect via the `${AuthStack}-FederationType` export *before* importing; if `cognito`, skip persona provisioning with a clear message (FR-2.7). **Decision D5.**
- **F8 — Inference profiles are consumed, never created;** Budgets don't exist. Both are net-new. AIP creation needs `bedrock:CreateInferenceProfile` on the *deploy* principal; persona roles need invoke on `application-inference-profile/*`.
- **F9 — Existing hardcoded names.** `QuotaPolicies`, `UserQuotaMetrics`, `claude-code-quota-alerts` are hardcoded (pre-existing `cfn-naming` debt). The persona stack **reuses those exact names** by import/reference; **new** resources we create follow `!Sub '${AWS::StackName}-*'` (we don't propagate the debt). Budget topic: `!Sub '${AWS::StackName}-budget-alerts'`.
- **F10 — `_create_config` in `package.py` is an explicit allowlist**, not a full dump. Persona block must be added there explicitly, and to `init.py`'s `wizard_fields`, or it won't serialize.

## 3. Decisions (ADR-style)

| # | Decision | Rationale | Alternatives rejected |
|---|----------|-----------|----------------------|
| **D1** | Persona stack is **Python-rendered** YAML, deployed via existing `CloudFormationManager` | CFN can't loop over N personas; repo already parameterizes templates Python-side | Static template + comma-delimited param + `Fn::Split` (can't express N distinct roles/policies cleanly); nested stacks (S3 staging overhead) |
| **D2** | Add `Profile.effective_auth_type` property | Satisfies `auth-type-compat.md`, one true check, backward-compatible | Scatter `getattr(sso_enabled)` (perpetuates the gap) |
| **D3** | Declared-order precedence **only in PBAC mode**; legacy path unchanged | Avoids changing enforcement semantics for existing non-persona deployments | Global switch to declared-order (breaks existing multi-group users) |
| **D4** | otel-helper resolves persona independently from `groups` + config | Decouples binaries; no fragile cache handshake; reuses existing claim+config load | Cross-binary cache file (race/IPC complexity) |
| **D5** | Direct-IAM only; Cognito detected & skipped via `FederationType` export | `groups` STS trust condition needs direct IAM; Cognito uses role mapping | Build Cognito role-mapping now (OOS-8) |
| **D6** | Personas = GROUP quota policies (identifier = `group` value) | Reuses shipped resolution + `set-group` CLI verbatim | New `PERSONA` PolicyType (needless schema churn) |
| **D7** | Separate `${AWS::StackName}-budget-alerts` SNS topic | Finance vs eng audiences; FR-6.2 | Reuse quota topic (interleaves signals) |
| **D8** | Persona Bedrock policy Allow **and** Deny span all 3 ARN shapes | FR-2.3 — cross-region inference-profile bypass is the #1 risk | foundation-model-only (silently bypassable) |
| **D9** | Personas serialized as `list[dict]` in `Profile` (not a nested dataclass) | Matches existing `monitoring_config` dict pattern; clean `from_dict` round-trip | Nested dataclass (complicates the field-filter on load) |

## 4. Data contracts (front-loaded so tasks run file-disjoint)

### 4.1 `config.yaml` / `Profile` persona schema (Group 1 produces; everyone consumes)

```python
# Profile gains (config.py):
personas: list[dict] = field(default_factory=list)
groups_claim_name: str = "groups"        # cognito:groups, roles, etc. per IdP
fallback_persona: str | None = None       # name of a persona, or None = hard-deny
# property:
@property
def effective_auth_type(self) -> str: ...  # "oidc" if sso_enabled else "none"  (see §0 A1 — no auth_type passthrough as shipped)
```

Each persona dict (canonical shape — **frozen contract**):
```yaml
- name: engineering            # identifier; DNS/IAM-safe; used in role name + policy id
  display_name: Engineering
  group: eng-team              # the value the OIDC `groups` claim must contain
  allowed_models:              # list of model-id globs; [] or ["*"] = all anthropic
    - "anthropic.*"
  denied_models: []            # explicit-deny globs (restricted personas)
  monthly_token_limit: 300000000
  daily_token_limit: null      # null = derive/none
  enforcement_mode: block      # alert | block
  budget_amount_usd: null      # null = no per-persona budget
  cost_tags: {Team: Engineering, CostCenter: CC-1001}
# top-level (siblings of personas):
# groups_claim_name, fallback_persona, account_budget_amount_usd
```

### 4.2 Go `PersonaConfig` (parity with §4.1 — **frozen**)

```go
type PersonaConfig struct {
    Name             string            `json:"name"`
    DisplayName      string            `json:"display_name,omitempty"`
    Group            string            `json:"group"`
    AllowedModels    []string          `json:"allowed_models,omitempty"`
    DeniedModels     []string          `json:"denied_models,omitempty"`
    RoleARN          string            `json:"role_arn"`            // resolved at package time
    MonthlyTokenLimit int64            `json:"monthly_token_limit,omitempty"`
    EnforcementMode  string            `json:"enforcement_mode,omitempty"`
    CostTags         map[string]string `json:"cost_tags,omitempty"`
}
// ProfileConfig gains:
//   Personas []PersonaConfig `json:"personas,omitempty"`
//   GroupsClaimName string   `json:"groups_claim_name,omitempty"`
//   FallbackPersona string   `json:"fallback_persona,omitempty"`
```
**Note:** each persona's `role_arn` is the per-persona role ARN, written into `config.json` by `ccwb package` after the persona stack is deployed (read from stack outputs). Empty `Personas` ⇒ fall back to `FederatedRoleARN` (today's behavior, untouched).

### 4.3 Persona resolution algorithm (shared by Go helper, both Lambdas, otel-helper — **identical logic**)

```
resolve_persona(user_groups: set, personas: ordered_list, fallback: str|None) -> persona|None:
    for p in personas:                 # DECLARED ORDER = precedence
        if p.group in user_groups: return p
    if fallback: return personas.by_name(fallback)
    return None                         # None => hard-deny (helper) / no-policy (lambda)
```
- Helper: `None` → exit non-zero with clear stderr (no role assumed).
- quota Lambda: `None` → existing user/default policy lookup still applies (persona is just the group tier). As shipped, the Lambdas use **declared-order via `PERSONA_ORDER`** rather than passing a Python set into this exact function; the *semantics* (first declared group wins; PBAC mode is sole authority, falls through to default) match §0 A5. `quota_monitor` resolves groups from the stored `USER#<email>/GROUPS` record (A5), `quota_check` from the JWT.
- This is the **parity contract** — a change in one implementation requires the same change in the others + parity tests.

### 4.4 Rendered persona stack — outputs (consumed by `package`)
Per persona `<name>`: `Output {name}RoleArn` = `!GetAtt {Name}Role.Arn`, exported `!Sub '${AWS::StackName}-{Name}-RoleArn'`. `package` reads these to populate §4.2 `RoleARN`.

### 4.5 CloudWatch persona dimension
otel-helper emits header `x-persona: <name>`; collector maps to metric label `persona` on `claude_code.token.usage`. Dashboards/queries group by `persona`.

## 5. Constraints & invariants (from `.claude/rules/`)

- **Tier-1 files touched** (`review-tiers.md`): `config.py`, `deploy.py`, `credential-process/main.go`, `internal/config/config.go`, plus new `bedrock-personas.yaml` (auth-template tier). Every changed path needs a regression test + backward-compat test + auth-type matrix (oidc/idc/none) + Go↔Python parity test.
- **Go↔Python parity** (`config-sync.md`, `credential-helper-parity.md`): §4.1↔§4.2 fields; `buildSessionName` **unchanged** (parity tests must still pass); persona resolution logic mirrored.
- **`bedrock:` namespace only** (`iam-actions.md`); never `bedrock-runtime:`.
- **No boto3 in credential-process** (`credential-recursion.md`): persona resolution is pure in-memory; STS direct call only.
- **Quota requires OIDC** (`quota-requires-oidc.md`): skip personas for `effective_auth_type != "oidc"`.
- **OTEL attribution chain** (`otel-attribution-chain.md`): `x-user-email` always present; `x-persona` excluded when empty.
- **CFN naming** (`cfn-naming.md`): new resources `!Sub '${AWS::StackName}-*'`; reuse existing hardcoded names only by reference.
- **Windows guards** (`windows-platform-guards.md`): `encoding="utf-8"` on all file IO; rendered YAML written utf-8; blocking Windows CI.
- **Region/partition** (`region-availability.md`): `${AWS::Partition}`; AIP/Budgets region-aware; Budgets SNS policy needs `aws:SourceAccount` confused-deputy guard.
- **Issuer/Azure** (`issuer-url-format.md`, `azure-tenant-extraction.md`): group trust-condition key is `<issuer-without-scheme>:groups`; never pass raw domain URLs as CFN params.
- **Branch/PR** (`branch-strategy.md`, `pr-standards.md`): target `beta`; this is a large feature so it lands on a `feat/persona-based-access` branch as a coherent series.

## 6. Scope guards
- **Out:** in-flight hard block, second invocation-logging pipeline, Terraform, all AI-DLC content, Cognito personas, `ccwb persona` subcommands (all per `requirements.md` OOS-1…9).
- **In:** FR-1…FR-10 including the `PBAC_README.md` deliverable + main README link.

## 7. Risks
| Risk | Mitigation |
|------|-----------|
| Inference-profile Deny bypass (R-highest) | D8 + the pytest `tests/test_persona_policy_bypass.py` (as shipped, §0 A4): renders the Sales persona and asserts the Deny covers sonnet/opus across all 3 ARN shapes **plus the region-less global-CRIS FM ARN** (§0 A9), with both a hardcoded-ARN meta-test and a renderer-mutation meta-test that a foundation-model-only Deny FAILS the check |
| Persona enforced only by Go helper; default package is legacy (§0 A9) | `package.handle()` hard-refuses a direct-federation persona profile built without `--go` (`_personas_require_go`); regression-tested. PBAC_README §4 documents `--go` as required for personas |
| Declared-order change regresses legacy quota | D3 PBAC-mode gating + regression test of legacy most-restrictive path |
| Rendered YAML invalid / un-lintable | Render a representative fixture committed to the repo; CI `cfn-lint`s it; unit-test the renderer output |
| Helper/Lambda/otel persona logic drift | §4.3 single algorithm + cross-impl parity tests (Group with shared fixtures) |
| Cold-start regression | Persona resolution is O(N) in-memory, no new deps; keep `<100ms` |
| Cognito deployment crashes on persona deploy | D5 FederationType pre-check + skip |
