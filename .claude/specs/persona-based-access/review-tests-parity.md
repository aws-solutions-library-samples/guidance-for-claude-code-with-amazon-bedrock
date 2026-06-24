# Review — `tests-parity` scope (reviewer: review-4)

Sole author: review-4. Scope per `review-plan.md` §Scope 4: the persona test suite + Go↔Python
parity oracle + docs. Implementation files are reviewed by review-1 (python-cli), review-2 (go-helper),
review-3 (infra-lambda).

## Cycle 1 — 2026-06-16
Reviewing: persona-based-access test suite + parity + docs [scope: tests-parity]

### Files reviewed (all read in full)
Python: `test_persona_resolution.py`, `test_persona_template.py`, `test_budgets_template.py`,
`test_persona_validation.py`, `test_persona_parity.py`, `test_persona_policy_bypass.py`,
`test_backward_compat_personas.py`, `test_lambda_persona_order.py`, `test_deploy_personas.py`,
`test_init_personas.py`, `test_package_personas.py`, `test_config.py` (persona additions),
`tests/fixtures/persona_resolution_cases.json`.
Go: `internal/persona/resolve_test.go`, `internal/config/personas_test.go`, `internal/jwt/decode_test.go`,
`cmd/credential-process/main_test.go`, `internal/otel/persona_header_test.go`, `cmd/otel-helper/main_test.go`.
Docs/meta: `assets/docs/QUOTA_MONITORING.md`, `.gitignore`.
Cross-scope (read to confirm bug-fix regression coverage, not owned): `tests/cli/commands/test_destroy_stacks.py`.

### Spec Alignment
All FR-9.4 / NFR-1 test gates are satisfied with genuine behavioral assertions:

- **§4.3 parity (the headline contract) is real, not self-consistent.** `test_persona_parity.py`
  runs the Python `resolve_persona` over every case in `persona_resolution_cases.json` AND shells
  out to the Go `TestResolveAgainstSharedFixtures`, which loads the *same* file
  (`source/go/internal/persona/resolve_test.go:14` → `../../../tests/fixtures/persona_resolution_cases.json`)
  and asserts the Go resolver yields each case's `expected`. Both implementations are pinned to one
  oracle ⇒ agreement on the fixtures is agreement with each other. The transitive argument is made
  explicit (`TestParityCrossCheck`). 12 fixture cases cover every algorithm branch: single-match,
  no-match±fallback, declared-order (both orderings), empty personas, empty groups±fallback,
  unknown-fallback→None, match-beats-fallback, case-sensitivity, extra-key tolerance.
- **No silent CI pass when Go is absent — VERIFIED by simulation.** `_go_binary()` raises
  `FileNotFoundError` (no `pytest.skip`/`skipif`/`importorskip` anywhere in the module — confirmed by
  grep); I monkeypatched `shutil.which→None` + all three fallback paths to non-existent and confirmed
  `TestGoSideMatchesFixtures` *errors* (blocks CI), never skips. `buildSessionName` is independently
  guarded (`TestBuildSessionNameUnchanged` shells `go test ./internal/federation/ -run SessionName`).
- **Bypass-guard (R-highest) HAS TEETH — VERIFIED by mutation.** I copied the renderer, set
  `_ARN_SHAPES` to foundation-model-only, and ran the actual coverage check the real test uses
  (`test_persona_policy_bypass.py::test_deny_covers_all_three_shapes_for_sonnet_and_opus`'s
  `_shapes_covered_for_keyword`): it correctly reports `inference-profile` and
  `application-inference-profile` missing. So the renderer→assertion pipeline (not just the
  hand-built meta-test `test_foundation_model_only_deny_would_fail_the_guard`) fails when a shape is
  dropped. The suite also independently asserts the *access-policy* Deny alone covers all 3 shapes
  (`test_access_policy_deny_is_self_sufficient`, keyed on `Sid=DenyBedrockInvokeDeniedModels`), so the
  boundary cannot mask a deficient access policy.
- **Backward-compat is genuine** (`test_backward_compat_personas.py`): a pre-persona profile dict
  (no persona keys) loads with `personas==[]`, `groups_claim_name=="groups"`, `fallback_persona is None`;
  `effective_auth_type` derives from legacy `sso_enabled`; `_create_config` emits **no** persona keys
  (so the Go helper falls back to `FederatedRoleARN`); and with `PERSONA_ORDER` unset the quota Lambdas
  return the most-restrictive policy (lowest limit) regardless of group order, guarded by
  `assert mod.PERSONA_ORDER == []`. The Go side mirrors this (`personas_test.go`:
  legacy round-trip omits persona keys; empty slice → no `"personas":null`).
- **Lambda declared-order covers BOTH modes for BOTH Lambdas** (`test_lambda_persona_order.py`):
  PBAC first-declared-wins (both orderings), legacy most-restrictive (unset + empty-string),
  single-group match, the D3 default-tier fallthrough for an undeclared group (decisions.md
  2026-06-15 "PERSONA_ORDER is the sole group authority"), user>group precedence, and a cross-Lambda
  agreement test. quota_check and quota_monitor are exercised symmetrically.
- **Every bug-fix-class change has a regression test:** #27 FR-9.5 teardown gap →
  `test_destroy_stacks.py::test_destroy_covers_every_deployable_stack` + `test_no_phantom_destroyable_stacks`
  (34 pass with `test_deploy_personas.py`); #28 singular `-persona` stack-name → `test_deploy_personas.py`
  asserts `args[1]=="test-pool-persona"` / `"test-pool-budgets"` / `"test-pool-persona-dashboard"`;
  #29 multi-line-append collapse → covered by the same destroy coverage test that originally caught it;
  #30 Auth0/Azure issuer-host (just-fixed CRITICAL) → `test_deploy_personas.py::TestResolveIssuerHost`
  asserts the exact trust key (`company.auth0.com/:groups` slash-preserved, Azure `/v2.0` no-slash) per
  `issuer-url-format.md`.
- **Parity-by-projection** (`test_package_personas.py::test_serialization_projects_only_42_fields`):
  asserts Python-only fields (`daily_token_limit`, `budget_amount_usd`) do **not** leak into config.json
  and `omitempty` empties are dropped — this is the §4.2 config-sync contract enforced from the Python side,
  complementing the Go round-trip in `personas_test.go`.
- **OTEL attribution chain** (`persona_header_test.go`): `x-user-email` ALWAYS present; `x-persona`
  empty-excluded on no-match; custom claim name + default-to-`groups`; `HeaderMapping["persona"]=="x-persona"`.
  Cache schema is `schema_version:3` in the otel-helper fixtures (matches the 2→3 bump).
- **Docs** (`QUOTA_MONITORING.md`): documents `PersonaOrder` param and the most-restrictive→declared-order
  switch, accurately reflecting D3. `.gitignore` correctly re-includes `source/tests/**` via the `!`
  negation (verified with `git check-ignore -v`).

### Test results (run locally)
- Full persona/parity scope: **197 passed** (`pytest tests/test_persona_*.py tests/test_budgets_template.py
  tests/test_backward_compat_personas.py tests/test_lambda_persona_order.py tests/test_deploy_personas.py
  tests/test_init_personas.py tests/test_package_personas.py tests/test_config.py -q`).
- Full Python suite: **1120 passed, 22 skipped, 1 xfailed, 1 xpassed, 0 failed** (78s). Confirmed by grep
  that **none** of the 22 skips / xfail / xpass are persona/parity tests (the lone XPASS is the unrelated
  pre-existing `test_credential_process_contract.py` refresh-token PR-#447 case). No persona test silently
  skips.
- Full Go suite: **all packages ok** including `internal/persona` and `internal/federation`
  (`go test ./... -count=1`).
- Plugin `feature-dev:code-reviewer` run over all 16 test files; findings triaged below.

### Critical
None.

### Warning
None.

### Suggestion
- [`test_persona_parity.py:46-50`] The `_load_cases()` coverage guard only asserts `len(cases) >= 5`.
  The oracle currently has 12 named cases covering distinct branches; if it silently shrank to 5 the
  parity proof would weaken with no signal. Consider pinning the *named* critical cases
  (`multi_match_first_declared_wins`, `no_match_no_fallback`, `match_takes_precedence_over_fallback`,
  `fallback_names_unknown_persona`, `empty_groups_with_fallback`) rather than a bare count.
  [via feature-dev:code-reviewer C2]
- [`test_persona_parity.py:86` vs `test_persona_resolution.py:29`] Fixture access is inconsistent:
  parity uses `case.get("fallback")` (defaults `None` if absent) while the resolution test uses
  `case["fallback"]` (raises if absent). All 12 cases carry the key today, so both pass; harmonize to
  `case["fallback"]` and extend `test_fixtures_define_a_single_expected_per_case` to also require
  `"fallback" in case`, so a future under-specified case fails loudly in both. [via feature-dev:code-reviewer W4]
- [`test_persona_template.py:141`] `test_sales_deny_spans_all_three_arn_shapes` checks only `deny[0]`.
  The renderer currently emits **exactly one** Deny per policy (verified: `SalesPolicy` →
  `DenyBedrockInvokeDeniedModels`, `SalesBoundary` → `BoundaryDenyDeniedModels`), so this is safe now,
  but a future split into multiple Deny statements could hide an incomplete one. Either assert
  `len(deny) == 1` first, or aggregate across all Deny statements as `test_persona_policy_bypass.py`
  does. (Security is still guarded — the dedicated bypass test aggregates and the access-policy
  self-sufficiency test exists.) [via feature-dev:code-reviewer W2]
- [`test_persona_policy_bypass.py:97-113`] `test_deny_covers_all_three_shapes_for_sonnet_and_opus`
  aggregates Deny ARNs across *both* the access policy and the boundary, so in isolation it would pass
  even if only the boundary covered a shape. This is already closed by the sibling
  `test_access_policy_deny_is_self_sufficient`, but tightening this test to the access-policy resource
  only would make each test self-contained. [via feature-dev:code-reviewer W1]
- [`test_lambda_persona_order.py:43`, `test_backward_compat_personas.py:132-143`] `_load_module` /
  `_load_quota_check` mutate `os.environ` (`QUOTA_TABLE`, `POLICIES_TABLE`, `ENABLE_FINEGRAINED_QUOTAS`,
  `SNS_TOPIC_ARN`, `PERSONA_ORDER`) with no teardown. The fresh-module-name trick (`id(env)`) keeps the
  *module* isolated and the full suite passes today (env keys are Lambda-specific and the conftest only
  pins AWS region), so this is **latent**, not active — but under `pytest-randomly` or a future test that
  reads these vars it could flake. Use `monkeypatch.setenv` / `patch.dict(os.environ, env)` so env is
  restored per-test. [via feature-dev:code-reviewer C3 — downgraded from Critical: verified no actual
  failure across 1120 tests]
- [`test_deploy_personas.py:203-221`] `test_deploy_failure_skips_seeding` leaves
  `_write_back_persona_role_arns` / `_deploy_persona_dashboard` unpatched. I confirmed in
  `deploy.py:1431-1432` that a failed deploy returns *before* any post-deploy step, so those methods are
  never reached and cannot raise — the test is correct. Adding `writeback.assert_not_called()` would
  pin that ordering against regression. [via feature-dev:code-reviewer W5 — not a defect, robustness only]
- [`test_deploy_personas.py:75-93`] `TestPersonaScheduling._schedule` re-implements the `handle()`
  scheduling block rather than driving the real method (the docstring says "Mirrors …"). The real gating
  (`effective_auth_type`/Cognito/OIDC-export) IS covered by the `_deploy_persona_stack` tests, so this is
  a duplicate-logic smell, not a coverage gap; consider asserting against the real scheduler.

### Cross-Task Consistency
- §4.2/§4.3 contract (Scope 1 Python ↔ Scope 2 Go ↔ Scope 4 oracle): the fixture is the single source
  of truth and both resolvers are pinned to it; struct-tag parity is round-tripped in `personas_test.go`
  and projection-checked in `test_package_personas.py`. Coordinated with review-1/review-2 below.
- PERSONA_ORDER seam (Scope 1 deploy.py compute ↔ Scope 3 lambda consume): `test_deploy_personas.py::
  TestComputePersonaOrder` proves declared-order join + dedup + empty-when-not-oidc on the compute side;
  `test_lambda_persona_order.py` proves consumption. Both ends tested; agree on comma-joined group values.
- x-persona seam (Scope 2 emit ↔ Scope 3 dimension): emit side tested in `persona_header_test.go`
  (empty-exclusion preserved). Collector-dimension consumption is review-3's file (out of my scope).

### Handoff note to the lead (NOT a scope FAIL)
All new persona test files, the parity fixture, and the committed CFN fixture are **untracked** in git
(expected — teammates don't commit; the lead handles git). `git check-ignore` confirms they are **not**
gitignored (the `!source/tests/**` negation works). When committing, `git add` MUST include every one of:
`source/tests/test_persona_*.py`, `test_backward_compat_personas.py`, `test_lambda_persona_order.py`,
`test_deploy_personas.py`, `test_init_personas.py`, `test_package_personas.py`, `test_budgets_template.py`,
`source/tests/fixtures/persona_resolution_cases.json`, `source/go/internal/persona/resolve_test.go`,
`source/go/internal/config/personas_test.go`, `source/go/internal/otel/persona_header_test.go`,
and `deployment/infrastructure/bedrock-personas.example.yaml`. Omitting the fixture or any Go parity test
would strip the cross-language oracle from CI silently. (The `__pycache__/*.pyc` under `source/tests/` are
correctly gitignored and should not be staged.)

### Tests
- [x] All tests passing (Python 1120 pass / 0 fail; Go all packages ok; persona scope 197 pass)
- [x] Test coverage adequate (parity genuine + fail-not-skip proven; bypass guard teeth proven by mutation;
      backward-compat real; both quota modes + both Lambdas; every bug-fix-class change has a regression test)

### Re-confirmation (post-build edit to test_deploy_personas.py)
The lead flagged that coding-1 edited `test_deploy_personas.py` during the #29 aftermath
(`test_happy_path_renders_deploys_and_seeds` now patches `_deploy_persona_dashboard` and asserts
`dashboard.assert_called_once()`; the stale "separate dashboard stack type" comment was corrected to the
INLINE design). This is the exact file state I reviewed in Cycle 1 (my notes already cite the dashboard
assertion). Re-confirmed it is a genuine behavioral assertion, NOT a vacuous mock: the call originates in
the real `_deploy_persona_stack` under test (`deploy.py:1446` `self._deploy_persona_dashboard(...)`); only the
collaborator is mocked, so a regression that dropped the inline dashboard call would fail this test.
Argument-correctness of the dashboard deploy is separately owned by `TestDeployPersonaDashboard` (asserts
`args[1]=="test-pool-persona-dashboard"` + `MetricsRegion=`). File is green (29 passed — includes #30's
Auth0/Azure issuer-host tests). `test_deploy_personas.py` line 2 is a 130-char `# ABOUTME:` header E501;
it is pre-existing-class debt and the file is NOT ruff-gated by any persona Run command — treated like the
init.py E501 allowlist per decisions.md, not a finding. Verdict unchanged.

### Verdict: PASS
All FR-9.4 test gates and NFR-1 parity/regression requirements are met with behavior-asserting tests. The
two highest-risk guards (Go↔Python parity oracle; 3-ARN-shape bypass guard) were verified by direct
mutation/simulation to have real teeth and to fail (not skip) when their dependency is absent. Remaining
items are Suggestions (test hardening); none block. One handoff note for the lead on `git add` completeness
at commit time.
