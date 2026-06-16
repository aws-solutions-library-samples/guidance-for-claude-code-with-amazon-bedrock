# Decision Log — Persona-Based Access Control

## 2026-06-15 — FR-5.1 per-persona model routing fully implemented (user-directed, post-review)
**Context:** The deep-dive review found FR-5.1 ("wire per-persona inference-profile ARNs into the helper's model routing") was only half-built — AIPs were tagged for cost attribution but their ARNs were never routed. The user directed full implementation (and the L-a GovCloud partition fix).
**Research (verified against AWS docs):** (1) an inference-profile **ARN is accepted as `modelId`** in InvokeModel/Converse → usable as `ANTHROPIC_MODEL`. (2) A **multi-Region AIP must `copyFrom` a cross-Region (system-defined) inference profile**, NOT a bare foundation model — the shipped code's single-region FM source would have broken CRIS routing. (3) The global `inference_profile_*_arn` fields were ALSO never wired into routing (dead config) — there was no existing mechanism to extend.
**Architecture decision (user chose "Full"):** personas resolve per-user at credential-issuance but `ANTHROPIC_MODEL` is static-per-bundle, so per-user routing is delivered by an **opt-in launch wrapper** that calls a new `credential-process --get-persona-model` (resolves persona from the cached token's groups claim → emits `ANTHROPIC_*_MODEL` exports). settings.json's baked model is the floor; the wrapper overrides per-launch when a persona matches (no match / expired / not sourced → unchanged → fully backward compatible).
**Build:** new `persona_models.py` (tier entitlement from allow/deny globs + AIP naming + partition-aware CRIS source — shared by deploy & destroy, single source of truth). deploy creates one AIP per **entitled tier** (`{pool}-{persona}-{tier}`), reads ARNs back into `persona["inference_profile_arns"]`, persists. Go `PersonaConfig.InferenceProfileArns` (parity). `package` serializes them + generates `persona-model.sh`/`.ps1` (CRLF). destroy deletes per-tier (+ legacy name). PBAC_README §7 rewritten; spec §0 A8.
**Tests:** Go `TestResolvePersonaModelExports` (9 cases); Python `test_persona_models.py` (12), AIP-creation tests (6, real method — previously mocked), wrapper+serialization tests (6).
**Reversibility:** additive + opt-in; removing the wrapper or the ARNs reverts to today's static routing.

## 2026-06-15 — Go toolchain absent; installed + cache warmed (resolved blocker)
**Context:** coding-3 reported (via tasks.md) that `go`/`gofmt` were not installed, blocking all 5 Go tasks (#5, #6, #9, #12, #14). `go.mod` requires Go 1.24.
**Investigation (lead):** Confirmed Go absent on PATH and in common locations, but Homebrew present. Installed `go` (1.26.4, satisfies 1.24). Found `proxy.golang.org` unreachable (no external module proxy), but `GOPROXY=direct` (git-based fetch) works. Ran `GOPROXY=direct go mod download all` → full module cache warmed → `go build ./...` and full `go test ./...` baseline suite PASS.
**Decision:** Installing the toolchain is standard, non-destructive environment setup within scope — resolved directly rather than escalating. All Go tasks verifiable as written (no need to weaken the credential-process `go build ./...` verification).
**Effect:** #5/#6/#9/#12/#14 unblocked. Teammates use the warmed cache; if a teammate hits a proxy timeout, they should set `GOPROXY=direct` (cache is already populated, so this is belt-and-suspenders).
**Reversibility:** Fully reversible (`brew uninstall go`); no repo changes.

## 2026-06-15 — Persona policy uses repo's action set (drop explicit `bedrock:Converse`)
**Context:** Task #10 text said Allow `InvokeModel/InvokeModelWithResponseStream/Converse/ConverseStream`. coding-3 instead emitted `InvokeModel/InvokeModelWithResponseStream/CallWithBearerToken` — the exact set the shipped `bedrock-auth-*.yaml` templates use.
**Decision (lead): APPROVED.** Bedrock authorizes the Converse API under `bedrock:InvokeModel` (no separately-enforced `bedrock:Converse` runtime IAM action); explicitly listing `bedrock:Converse` trips cfn-lint W3037 against its stale action DB. Dropping it is functionally identical, matches repo convention, and keeps the rendered stack lint-clean. **Security check:** this does NOT weaken restricted-persona Deny — a Deny on `bedrock:InvokeModel` for sonnet/opus resource ARNs also blocks Converse-to-sonnet, since Converse runs under InvokeModel. Existing production templates prove Claude Code works with this exact action set.
**Reviewer note:** flagged for review-agent to re-confirm the Allow/Deny action set matches `bedrock-auth-generic.yaml` and that no model-access path escapes the Deny.
**Reversibility:** trivial (add the actions back with a `--ignore-checks W3037` note) if a reviewer objects.

## 2026-06-15 — PERSONA_ORDER is the sole group authority in PBAC mode (devops-1, #18)
**Context:** In PBAC mode (PERSONA_ORDER set), the quota Lambdas resolve a user's group policy by declared order. devops-1 surfaced a subtlety: what if a user's only matching group policies are NOT listed in PERSONA_ORDER?
**Decision:** When PERSONA_ORDER is set, it is the **sole authority** for group→policy resolution — a user whose groups are none of the declared personas falls through to the DEFAULT quota tier (NOT back to legacy most-restrictive over their other groups). This is consistent with the helper's persona resolution (no persona match → fallback/deny) and avoids a confusing hybrid. When PERSONA_ORDER is unset (legacy/no personas), the original most-restrictive `min()` behavior is preserved byte-for-byte.
**Integration contract (REQUIRED):** deploy.py (#15) must pass `PersonaOrder` (CFN param, comma-joined persona `group` values in declared order) to the quota stack (#19 adds the param → `PERSONA_ORDER` env on both Lambdas). If deploy.py omits it, the enforcement change is inert (Lambdas stay legacy). Tracked on #15 + #19.
**Doc:** PBAC_README must document PERSONA_ORDER as the knob that flips group resolution from most-restrictive → declared-order, and the default-tier fallthrough behavior.
**Reviewer note:** infra-lambda reviewer to confirm the legacy path is unchanged when PERSONA_ORDER is empty.

## 2026-06-15 — Pre-existing init.py E501 lines are NOT in scope (review note)
**Context:** coding-2 flagged that `init.py` carries ~14 pre-existing ruff E501 (long-line) warnings unrelated to PBAC, and deliberately did not `ruff format` the whole file (would churn dozens of out-of-scope lines).
**Verified (lead):** `ruff --select E501` shows **14 at HEAD and 14 in the working tree** — coding-2 introduced ZERO new E501. Confirmed pre-existing.
**Decision:** Out of scope for this feature (one-concern-per-PR, pr-standards.md). Do NOT let the review pool FAIL the group or attribute these to PBAC. A formatting-only pass on init.py can be a separate chore PR if desired.
**Review note:** python-cli reviewer — init.py E501s are pre-existing; only assess PBAC-introduced lines.

## 2026-06-16 — Low-issue wave (user-decided, single implementation pass)
After the deep-dive, the user reviewed each Low with new-in-branch-vs-pre-existing provenance and decided:
- **L1 (FIXED, minimal):** `effective_auth_type` is net-new in this branch; its `auth_type` passthrough was dead (from_dict filters the non-field key). Dropped the dead branch → derives purely from `sso_enabled`; docstring updated; test rewritten to document the filtered behavior. (Pre-existing `deploy.py:1014` idc-path on main left untouched — out of scope.)
- **L2 (SKIPPED):** Cognito issuer-host pool-region logic is pre-existing on main AND unreachable via PBAC (direct-IAM only). Not ours, not activated by this branch.
- **L3 (FIXED):** package.py `_create_config` now gates persona serialization on `federation_type == "direct"` — no dead persona data under Cognito. New regression test.
- **L4 (FIXED):** `otel-helper.sh` sidecar shim now honors the cache `schema_version` gate (falls through to the binary when < CACHE_SCHEMA_VERSION=3). The shim is pre-existing, but THIS branch's 2→3 bump is what it was undermining. bash -n clean; gate logic traced.
- **L5 (FIXED, substantive):** per-persona ALERTING now works. quota_check persists `USER#<email>/GROUPS` (TTL 90d, best-effort, scoped IAM PutItem added to QuotaCheckRole); quota_monitor reads it via `get_user_groups` and passes the groups into `resolve_user_quota` so its (previously dead) declared-order branch resolves persona alert thresholds. Distinct `sk` keeps the record out of the monitor's MONTH# usage scan. 5 new lambda tests + the cross-Lambda parity check still green.

**Wave re-gate: Python 1136/0, Go 10/10, cfn-lint W3002 unchanged (3=3), config.py+deploy.py ruff-clean** (package.py's 23 E501 are pre-existing, 23@HEAD=23 now). PBAC_README §10 updated for the L5 alerting behavior.

## 2026-06-16 — Independent post-build deep-dive review + fixes (user-requested)
After team teardown, the user requested an independent deep-dive of the whole `rubab-dev1` PBAC diff. Ran 3 parallel skeptical reviewers (Go / Python-CLI / CFN-Lambda) over the actual code + a lead read of the highest-risk surfaces. Findings + fixes:

**HIGH — H1 (FIXED):** `_resolve_issuer_host` derived the persona trust-condition issuer-host from `provider_domain` for **generic OIDC** providers, but the generic auth template registers the OIDC provider from `oidc_issuer_url` (a DISTINCT field, often with a realm path). Mismatch → silent hard-deny for ALL generic-provider persona users — including **Teleport**, the original motivating use case. Same bug class as the Auth0 CRITICAL. Fix: generic branch in `_resolve_issuer_host` now uses `oidc_issuer_url` (scheme-stripped, path preserved). Regression test `test_generic_uses_oidc_issuer_url_not_provider_domain` (would fail on old code). Fixed the misleading `test_generic_issuer_scheme_stripped` that masked it (it had set provider_domain to the issuer value).

**MEDIUM — M1 (FIXED):** `validate_personas` was only called in the init wizard, never in the deploy path. A hand-edited config.yaml with a bad `enforcement_mode` (e.g. "deny" typo) silently downgraded block→alert in `_seed_persona_group_policies`. Fix: `_deploy_persona_stack` now calls `validate_personas` after the gate and fails (rc=1) with the collected errors before rendering. Regression test `test_invalid_persona_fails_before_render`.

**MEDIUM — M2 (FIXED, proportionate):** persona removed from config.yaml orphaned its inference profile + left a stale GROUP quota policy (create/destroy iterate only CURRENT personas, no pruning). Chose NOT to auto-delete (billing/quota resources shouldn't be implicitly removed by a deploy). Fix: deploy now DETECTS orphaned `{pool}-*` inference profiles and prints the exact `aws bedrock delete-inference-profile` command; PBAC_README §10 documents persona-removal cleanup (incl. `ccwb quota delete group <g>` for the stale limit).

**LOW (flagged to user, NOT fixed — await decision):**
- L1: `effective_auth_type`'s `auth_type` passthrough is dead (from_dict filters the non-field key); harmless today (nothing sets idc via auth_type).
- L2: Cognito-IdP cross-region issuer-host edge (pool-region vs stack-region); pre-existing, uncommon.
- L3: personas serialized into config.json even under Cognito federation (dead data; Go ignores it).
- L4: otel-helper sidecar `.raw` shim bypasses the cache schema-version gate → x-persona telemetry staleness window in collector/sidecar mode (pre-existing; access control unaffected).
- L5: quota_monitor's persona/group branch is dead in production (called with groups=[]) → per-persona ALERTING not delivered, only per-persona ENFORCEMENT (quota_check). Pre-existing; the PBAC story is half-delivered on alerting. Candidate follow-up: persist a user→group map at check time so the monitor can resolve persona alert thresholds.

**Doc alignment:** PBAC_README §3 gained a Generic/Teleport issuer-host row (the H1 fix) + §13 generic troubleshooting row; §10 gained a persona-removal/orphan-cleanup row.

**Re-gate after fixes: Python 1130/0 (+2 regression tests), Go 10/10. deploy.py ruff-clean.**

## 2026-06-16 — Two issuer forms are DIFFERENT (token-validation vs persona-trust)
**Context:** Lead accuracy-checked PBAC_README.md §3 against code and caught a factual error: the Okta row listed issuer-host `company.okta.com/oauth2/default`. WRONG for the persona trust condition.
**Ground truth (two distinct issuer forms — do not conflate):**
- **Token-VALIDATION issuer** (`_resolve_oidc_config` → `oidc_issuer`): used for JWT validation at the ALB/quota-check. Okta = `https://company.okta.com/oauth2/default`, Auth0 = `https://company.auth0.com/`, Azure = `https://login.microsoftonline.com/<tid>/v2.0`.
- **Persona TRUST-CONDITION issuer-host** (`_resolve_issuer_host` → STS `<host>:groups` key): MUST equal the IAM OIDC-provider `Url` the auth template registers, scheme-stripped. Okta registers `https://${OktaDomain}` → **bare `company.okta.com`** (NO /oauth2/default); Auth0 `https://${Auth0Domain}/` → `company.auth0.com/` (slash); Azure → `.../v2.0`.
**Why it matters:** these differ for Okta specifically (validation has /oauth2/default; trust-condition is bare). Pinned by `test_okta_bare_domain_no_slash` (asserts `== "company.okta.com"`) and the deploy.py:1329 docstring. README §3 Okta row corrected to bare domain (#33).
**Lesson:** accuracy-checking docs against code (not rubber-stamping) caught this — same high-stakes class as #30. The two issuer forms are a genuine footgun for anyone touching issuer logic.

## 2026-06-16 — Fix cycle complete + authoritative re-gate GREEN
All 3 fix tasks landed and lead-verified via full re-gate:
- **#30 (CRITICAL)** issuer-host: DONE — scheme-strip-only, Auth0 slash + Azure /v2.0 preserved, teethed regression tests.
- **#31 (WARNING)** account-budget: DONE — Profile field + wizard + wizard_fields + round-trip test.
- **#32 (WARNING)** dashboard teardown: DONE (coding-2) — explicit `_delete_persona_dashboard_stack`, no DESTROYABLE_STACKS phantom, L158 dead-ref removed; review-3 second-confirmed "no regression, no FR-9.5 gap".
**Authoritative re-gate (lead-run): Python 1128 passed / 0 failed; Go all 10 packages ok / 0 failed.** ruff clean on config.py/deploy.py/destroy.py; init.py 14 E501 pre-existing (allowlisted). review-4 confirmed coding-1's test-fidelity edit non-vacuous.
**Review board:** go-helper ✅ PASS · infra-lambda ✅ PASS · tests-parity ✅ PASS · python-cli → Cycle-2 verdict pending (all 3 findings fixed). Awaiting review-1 Cycle-2 to clear the final scope.

## 2026-06-16 — COMMIT MANIFEST (review-4 handoff hazard — git add ALL of these)
review-4 flagged: the new files below are UNTRACKED but NOT gitignored. A commit using `git add -u` (tracked-only) would SILENTLY STRIP the cross-language parity oracle + bypass fixture from CI. When the user authorizes commit, `git add` MUST include every path:

**Untracked (24) — new files:**
- Python src: `persona_resolution.py`, `persona_template.py`, `budgets_template.py`, `persona_validation.py`, `persona_defaults.py`
- Python tests: `tests/test_persona_resolution.py`, `test_persona_template.py`, `test_budgets_template.py`, `test_persona_validation.py`, `test_persona_parity.py`, `test_persona_policy_bypass.py`, `test_backward_compat_personas.py`, `test_lambda_persona_order.py`, `test_deploy_personas.py`, `test_init_personas.py`, `test_package_personas.py`
- **Parity oracle (CRITICAL to include):** `tests/fixtures/persona_resolution_cases.json`
- Go tests: `go/internal/persona/` (resolve.go + resolve_test.go), `go/internal/config/personas_test.go`, `go/internal/otel/persona_header_test.go`, `go/cmd/credential-process/main_test.go`
- Infra: `deployment/infrastructure/bedrock-personas-dashboard.yaml`, `bedrock-personas.example.yaml`
- Tooling: `source/poetry.toml`
- (EXCLUDE: `__pycache__/`, `.poetry-bootstrap/` — gitignored/build noise)

**Modified (24) — tracked:** `.gitignore`, `assets/docs/QUOTA_MONITORING.md`, `lambda-functions/quota_{check,monitor}/index.py`, `logs-insights-queries.yaml`, `otel-collector.yaml`, `quota-monitoring.yaml`, `cli/commands/{deploy,destroy,init,package}.py`, `config.py`, `go/cmd/credential-process/main.go`, `go/cmd/otel-helper/main{,_test}.go`, `go/go.sum`, `go/internal/config/config.go`, `go/internal/jwt/decode{,_test}.go`, `go/internal/otel/{cache,extract,headers}.go`, `tests/cli/commands/test_destroy_stacks.py`, `tests/test_config.py`

Verified all 24 untracked are stageable (none gitignored). `git add source/ deployment/ assets/ .gitignore` covers it; `git status` should show 0 untracked persona files before commit.

## 2026-06-16 — Review Cycle 1 verdicts + fix cycle (#30 CRITICAL, #31 WARNING)
**Consolidated verdict: FAIL (one scope).** Parallel 4-scope review:
- **go-helper (review-2): PASS** — 0 crit / 0 warn / 1 cosmetic suggestion (hard-deny error wording). §4.2/§4.3 parity exact + CI-enforced, buildSessionName byte-unchanged, backward-compat + attribution chain intact.
- **infra-lambda (review-3): PASS** — 0 crit / 0 warn / 2 non-blocking suggestions (both pre-existing, per allowlist). D3 legacy path byte-equivalent; R-highest 6-combo Deny confirmed in fixture; otel-collector closes the dashboard gap.
- **python-cli (review-1): FAIL** — 3 blocking WARNINGs (W1 elevated to CRITICAL by lead). R-highest (3-ARN Deny + teethed bypass test), Cognito skip, stack-ordering, PERSONA_ORDER compute, role_arn write-back, §4.2 serialization all confirmed correct. review-1 also correctly DISMISSED a plugin-reviewer false-positive ("StringEquals on aws:RequestedRegion CommaDelimitedList = always-deny" — wrong; CFN expands the list to a JSON array that StringEquals OR-matches, identical to shipped auth templates).
- **tests-parity (review-4): pending** at time of writing.

**Three fix tasks (Phase 3), all file-disjoint, concurrent:**
- **#30 (CRITICAL, W1)** issuer-host Auth0/Azure trust-condition → coding-3 (deploy.py).
- **#31 (WARNING, W2)** account_budget_amount_usd not wired through Profile/wizard → coding-3 (config.py/init.py).
- **#32 (WARNING, W3)** inline persona-dashboard CFN stack `{pool}-persona-dashboard` orphaned by destroy (FR-9.5) → coding-2 (destroy.py). Cleanest fix = explicit `_delete_persona_dashboard_stack` mirroring `_delete_persona_inference_profiles` (avoids the phantom-test trap of adding it to DESTROYABLE_STACKS). NOTE: distinct from review-3's L158 cosmetic dead-code SUGGESTION — the L158 skip-guard string becomes live once #32 wires the actual teardown.
On completion: full-suite re-gate + review-1 Cycle-2 re-review of ONLY the changed surface. go-helper/infra-lambda stay PASS (their files unchanged); tests-parity verdict pending.

**CRITICAL (#30):** `_resolve_issuer_host` (deploy.py) does `rstrip("/")`, stripping the trailing slash Auth0's STS web-identity condition key requires (provider registered `https://${Auth0Domain}/`). → persona trust emits `company.auth0.com:groups` but STS keys on `company.auth0.com/` → ALL Auth0 persona users silently hard-deny. Azure `/v2.0` same risk, no test. Auth0+Azure are FR-2.7 v1-supported. Authority: issuer-url-format.md. Lead verified + confirmed CRITICAL. Fix: derive condition-key from exact provider URL form (preserve Auth0 slash / Azure /v2.0), scheme-stripped only; Auth0+Azure regression tests.

**WARNING (#31):** `account_budget_amount_usd` read by deploy.py:1642 but not a Profile field / not wizard-collected / not in wizard_fields → FR-6.1 account-total budget unreachable. Fix: add field + wizard + wizard_fields + round-trip test.

**Routing:** both → coding-3 (deploy.py + config/wizard owner), file-disjoint (#30 deploy.py, #31 config.py+init.py). On completion: full-suite re-gate + review-1 re-reviews ONLY the changed surface. Other 3 scopes do not need re-review unless their files change.

## 2026-06-16 — #29 two-writer collision → resolved on INLINE design (lead verified green)
**Context:** My earlier mis-attribution (I told coding-2 "your #15" — #15 is coding-3's) seeded a routing storm; the idle-check then pushed coding-1 onto #29 while coding-3 was editing the same files (deploy.py + test_deploy_personas.py) → two writers thrashing between an INLINE design (`_deploy_persona_dashboard` called inside `_deploy_persona_stack`) and a STANDALONE stack-type design (`_deploy_persona_dashboard_stack`).
**Resolution:** coding-1 released #29 (did not clobber). coding-3 owned it through to completion on the **inline design**. Lead verified the settled tree from outside (not mid-edit): full Python suite **1120 passed / 0 failed**, `test_deploy_personas.py` + `test_destroy_stacks.py` = 34 passed together, ruff clean on deploy.py + destroy.py, Go 10 pkgs ok. The `persona-dashboard` refs that remain are legitimate (orphan-stack detection helper), not dead standalone scaffolding.
**Lead errors to own:** (1) mis-attributed #15 ownership → routing storm; (2) briefly offered to hand-fix deploy.py before realizing a second writer was live (withdrew before editing). Lesson: verify task ownership against the task store before routing contracts; never offer to edit an owned file that's `in_progress` without confirming the owner is clear.
**Design chosen:** INLINE persona-dashboard deploy (within `_deploy_persona_stack`, after budgets). No new top-level stack type. Reviewer (python-cli) to confirm the inline design is coherent and the `_check_orphaned_stacks` persona-dashboard refs are intentional.

## 2026-06-16 — #29 multi-line append broke a coverage test (regex blind spot)
**Context:** #29 added the persona stack as a distinct `persona-dashboard` stack type (in DESTROYABLE_STACKS, consistent) but also reformatted the `persona` append in deploy.py to a MULTI-LINE `stacks_to_deploy.append(\n  ("persona", ...)\n)`. `test_destroy_stacks._deployable_stack_types()` detects deployable types via a single-line regex `append\(\(\s*"name"`, so it missed the multi-line `persona` → `test_no_phantom_destroyable_stacks` FAILED ('persona' looked like a phantom in destroy). The CODE is correct (persona is deployed and destroyed); only the test's static detection was blind.
**Decision:** Fix = collapse the `persona` append to single-line (matches every other append; zero behavior change; no test weakening). Routed to coding-3 (deploy.py owner) as part of closing #29.
**Reviewer note (tests-parity):** the regex-based `_deployable_stack_types()` is fragile — it silently can't see multi-line `.append()` forms. Consider hardening it (AST or multi-line regex) so a future wrapped append doesn't reintroduce a false phantom/coverage miss. Flagging, not fixing now (single-line fix is correct + conventional).

## 2026-06-16 — Persona stack-name must agree deploy↔destroy (singular `-persona`)
**Context:** During #27, coding-3 found a naming mismatch they'd introduced in #15: deploy used `{pool}-personas` (plural) but destroy derives `{pool}-{stack_type}` = `{pool}-persona` (singular) → destroy would not find/tear down the deployed stack (silent FR-9.5 teardown miss).
**Resolution:** Fixed deploy.py to use singular `-persona` so deploy and destroy agree (deploy.py:1400 note documents this). Also added best-effort `_delete_persona_inference_profiles` in destroy (AIPs are created via boto3 outside the CFN stack, so stack-delete alone wouldn't remove them).
**Lead verification:** Confirmed no plural `-personas` STACK-NAME leftovers remain. The one `-personas` at deploy.py:1455 is the persona-dashboard's `DashboardName` PARAMETER value (cosmetic CloudWatch display name), NOT a stack name — the dashboard stack name (1451-1452) is correctly `persona-dashboard`. Not a bug.
**Reviewer note (infra/python-cli):** verify deploy/destroy/package all derive the persona stack name identically (singular). The dashboard display-name plural is intentional/cosmetic.

## 2026-06-16 — destroy.py teardown gap caught by #25 pre-check (FR-9.5)
**Context:** Lead ran the full Python suite as a #25 pre-check. `test_destroy_stacks.py::test_destroy_covers_every_deployable_stack` FAILED: deploy.py (#15) added `persona`+`budgets` deployable stack types, but `destroy.py` DESTROYABLE_STACKS wasn't updated — a real orphaned-stack bug and an FR-9.5 violation (`ccwb destroy` must tear down persona roles + budgets). No per-task test caught it (it's a cross-file invariant); the repo's own coverage test did.
**Decision:** Created fix task #27 (add budgets+persona to DESTROYABLE_STACKS in reverse-dep order: budgets→persona→…→auth-last); #25 now depends on #27. Validates the value of the integration-gate pre-check.
**Lesson:** The task decomposition should have paired every "add a deployable stack type" with a "destroy it" task. Folded into review focus.

## 2026-06-15 — Resolution logic lives in stdlib-only `persona` package
**Context:** `cmd/credential-process` transitively imports the AWS SDK (via `internal/federation`).
**Decision:** Persona role-selection logic (`selectRoleARN`/`Resolve`) lives in `internal/persona` (stdlib-only), so it is offline-testable and reusable by otel-helper. credential-process calls into it. Keeps the testable unit independent of the SDK-linked binary. (Reinforces spec §5 / design §2.6.)
