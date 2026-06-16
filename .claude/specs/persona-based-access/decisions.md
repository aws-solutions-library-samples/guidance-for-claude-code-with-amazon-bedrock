# Decision Log — Persona-Based Access Control

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
