# Review — Scope 3: `infra-lambda`

> Reviewer: review-3 · Sole author of this file.
> Scope: CloudFormation templates + Lambda enforcement (Tier 1/2).
> Files: `lambda-functions/quota_check/index.py`, `lambda-functions/quota_monitor/index.py`,
> `quota-monitoring.yaml`, `otel-collector.yaml`, `bedrock-personas-dashboard.yaml`,
> `logs-insights-queries.yaml`, `bedrock-personas.example.yaml`.

## Cycle 1 — 2026-06-15
Reviewing: Persona-Based Access Control — infra + lambda enforcement [scope: infra-lambda]

Baseline for "PBAC-introduced vs pre-existing": pre-PBAC commit `e2d4057`. All diffs and
cfn-lint deltas below are measured against it. PBAC work landed in `e03ddf4` + working tree.

### Spec Alignment
- **D3 (declared-order only in PBAC mode)** — SATISFIED. Both Lambdas gate declared-order on a
  non-empty `PERSONA_ORDER`; when empty, the legacy `min()` most-restrictive path runs. Verified
  byte-for-byte equivalent to baseline (see Critical analysis below — none found).
- **Decisions.md "PERSONA_ORDER is the sole group authority in PBAC mode"** — SATISFIED. When
  `PERSONA_ORDER` is set and none of the user's group policies are in it, both Lambdas fall
  through to the DEFAULT tier (not back to most-restrictive). `quota_check` L320-321,
  `quota_monitor` L333. Matches the helper's no-persona-match → fallback/deny semantics.
- **FR-7 (close empty-dashboard gap via otel-collector)** — SATISFIED. `x-persona` → `persona`
  upsert present in BOTH embedded collector configs (analytics L387-389, OTLP-only L506-508) and
  the `[[persona, OTelLib]]` EMF dimension present in the analytics block (L437-438). OTLP-only
  block correctly has no EMF exporter, so no dimension needed there.
- **FR-2.3 / EC-1 / D8 (3-ARN-shape Deny — R-highest)** — SATISFIED. See Cross-Task Consistency.
- **FR-9.4(c) (Sales can invoke Haiku)** — SATISFIED. Sales Allow uses `inference-profile/*anthropic.*haiku*`
  (leading `*` matches cross-region `us./eu./apac.` profiles).
- **PersonaOrder integration contract (#15 ↔ #19)** — my side ready: `quota-monitoring.yaml`
  `PersonaOrder` param (default `''`) → `PERSONA_ORDER` env on BOTH Lambdas (L240-241, L415-416).
  deploy.py-must-pass-it is review-1's seam; coordinated via SendMessage.

### Critical
None.

**D3 legacy-path byte-for-byte verification (the gating concern):**
Both resolvers were refactored from a `list` of group policies to a `dict {group: policy}`, then
`min(group_policies, key=...)` → `min(policies_by_group.values(), key=...)`. This is **semantically
identical** in legacy mode:
- Same set of policy objects (dict keyed by distinct group names; no policy dropped).
- Same `key` function (`monthly_token_limit`, `float("inf")` default in quota_check).
- Same tie-break: Python `min` returns the first minimum in iteration order; dict insertion order
  == the `groups` iteration order == the old list build order. Identical winner on ties.
Confirmed via `git diff e2d4057` on both files — the only behavioral branch added is guarded by
`if PERSONA_ORDER:` (empty in legacy/non-persona deployments).

### Warning
None.

### Suggestion
- [`lambda-functions/quota_monitor/index.py:223`] `resolve_user_quota(email, [], policies_cache)`
  passes an **empty groups list**, so neither the PBAC declared-order branch nor the legacy
  group-tier `min()` ever fires in the monitor — it always falls through to the DEFAULT/env policy
  for threshold/alert evaluation. This is **pre-existing behavior** (baseline `e2d4057` also passed
  `[]` at this call site) and therefore **not a PBAC regression**: the monitor scans
  `UserQuotaMetrics` by email and has no JWT/group context. Authoritative enforcement is
  `quota_check` (real-time, receives JWT groups, resolves persona correctly); the monitor is
  best-effort alerting. Net effect: group/persona-scoped users may be alerted against the default
  limit rather than their persona limit. Worth a follow-up (persist group on the usage record, or a
  user→groups lookup) but out of scope for this feature and not a blocker. The `PERSONA_ORDER`
  plumbing in the monitor is harmless-but-inert until groups are supplied.
- [`bedrock-personas-dashboard.yaml`] The "Estimated Cost by Persona" widgets depend on a
  `claude_code.cost.usage` metric carrying a `persona` label; cost emission/labeling is upstream of
  this scope. Consistent with the existing `claude-code-dashboard.yaml` cost widgets, so no new
  risk — noting the dependency only.

### Cross-Task Consistency
- **R-highest bypass guard (`bedrock-personas.example.yaml`)** — VERIFIED programmatically. The
  Sales explicit Deny covers **all 6** combinations (sonnet × {foundation-model, inference-profile,
  application-inference-profile}, opus × same 3) in BOTH `SalesPolicy` Deny (L114-120) and the
  `SalesBoundary` Deny (L166-172, defense-in-depth). Sales Allow is haiku-only (no sonnet/opus
  leakage). The customer-guide foundation-model-only gap is NOT reproduced. Deny is unconditional
  (no `aws:RequestedRegion`), so it cannot be sidestepped by requesting a non-listed region.
- **Action-set parity (decisions.md re-confirm)** — VERIFIED. Example fixture Allow/Deny use
  `bedrock:InvokeModel`, `InvokeModelWithResponseStream`, `CallWithBearerToken` — identical to
  `bedrock-auth-generic.yaml`. `bedrock:Converse` correctly omitted (runs under InvokeModel; the
  Deny on InvokeModel for sonnet/opus ARNs blocks Converse-to-sonnet/opus). No model-access path
  escapes the Deny.
- **`bedrock:` namespace only** — VERIFIED. Zero `bedrock-runtime:` occurrences across all scope
  templates.
- **Partition/GovCloud (NFR-8)** — VERIFIED. `bedrock-personas.example.yaml` uses `${AWS::Partition}`
  in all 21 ARN constructions; zero hardcoded `arn:aws:` literals.
- **cfn-naming — NEW resources** — VERIFIED. New persona resources export
  `!Sub '${AWS::StackName}-{Name}-RoleArn'`; new `PersonaOrder` param adds no named resource; new
  dashboard uses a parameterized `DashboardName`. The pre-existing hardcoded names
  (`QuotaPolicies`, `UserQuotaMetrics`, `claude-code-quota-alerts`, `claude-code-otel-cluster`,
  `otel-collector-alb`) are **untouched by the PBAC diff** and are intentionally preserved per spec
  §2 F9 (cross-stack import targets) — pre-existing debt on the lead's allowlist, NOT re-flagged.
- **x-persona seam (collector ↔ otel-helper, with review-2)** — CONSISTENT. otel-helper
  `headers.go:16/34` maps `persona`→`x-persona` from `info.Persona` (empty on no-match →
  `FormatHeaders` omits it); collector consumes `metadata.x-persona`. Header→label→widget chain
  intact. Confirmed to review-2.
- **PERSONA_ORDER seam (yaml/lambda ↔ deploy.py, with review-1)** — my side ready; flagged to
  review-1 to confirm deploy.py passes `PersonaOrder` (else the enforcement change is inert).

### cfn-lint
- `bedrock-personas.example.yaml` — **clean** (exit 0). The committed CI fixture lints as a real
  rendered artifact (DD-3).
- `bedrock-personas-dashboard.yaml` — **clean** (exit 0).
- `otel-collector.yaml` — **clean** (exit 0).
- `logs-insights-queries.yaml` — **clean** (exit 0).
- `quota-monitoring.yaml` — **3× W3002** (L243/335/417), the `Code: ./lambda-functions/...`
  packaging warnings. Verified identical to baseline `e2d4057` (3× W3002 at L230/322/402, same three
  `Code:` properties, shifted only by the PBAC param/env additions). **Zero new findings introduced
  by PBAC.** On the lead's pre-existing-debt allowlist — not flagged.
- cfn-lint binary: `source/.venv/bin/cfn-lint` 1.51.0.

### Plugin Review Synthesis (`feature-dev:code-reviewer`)
Ran on all 7 files. Findings triaged against the git baseline + decisions.md:
- Sales Deny ARN-shape coverage — reviewer CONFIRMED all 6 present (agrees; PASS).
- quota_monitor empty-groups — captured as Suggestion above; reviewer rated it a bug at 95, but it
  is pre-existing (baseline passes `[]` at the same call site) and the monitor is best-effort
  alerting — not a PBAC regression, not a blocker.
- `update_quota_metrics` day-rollover race — **out of scope**: `update_quota_metrics` is NOT in the
  PBAC diff (pre-existing code, untouched). Dropped as a PBAC finding.
- Hardcoded `TableName`/`ClusterName`/`TopicName`/ALB `Name` — **out of scope**: all present
  verbatim at baseline, untouched by PBAC, intentionally retained per spec §2 F9. Dropped (would
  violate the don't-re-flag-pre-existing-debt instruction).

### Tests
- [x] cfn-lint passes on all scope templates (only the 3 pre-existing allowlisted W3002).
- [x] D3 legacy path proven unchanged vs baseline (diff + min/dict-order equivalence argument).
- [x] Test coverage adequate for this scope: lambda declared-order vs legacy and the example
      fixture's Deny-shape coverage are exercised by `test_lambda_persona_order.py` /
      `test_persona_*` — owned/asserted by review-4 (tests-parity). My scope is the templates +
      lambda source, which are verified here directly.

### Cross-scope note (lead-delegated): `destroy.py:158` dead `persona-dashboard` tuple entry
> `destroy.py` is in review-1's `python-cli` scope; assessed here at the lead's explicit request
> (found during #29 post-collision verification) and noted for a fix cycle or conscious acceptance.

**Severity: SUGGESTION** (cosmetic dead code, zero behavioral impact — not a Warning/Critical).

Verified against the code: the skip-guard tuple at `destroy.py:158`
`if stack in ("persona", "budgets", "persona-dashboard") and not getattr(profile, "personas", [])`
contains `"persona-dashboard"`, but `DESTROYABLE_STACKS` (L27-40) lists only `"persona"` and
`"budgets"` — **not** `"persona-dashboard"`. Both populators of the loop's `stacks_to_destroy` are
bounded by `DESTROYABLE_STACKS` (L94 validates `stack_arg in DESTROYABLE_STACKS`; L101 is
`list(DESTROYABLE_STACKS)`), so the loop variable can never equal `"persona-dashboard"`. The tuple
element is therefore **provably unreachable** — a leftover from the abandoned standalone-dashboard
design (decisions.md #29, inline-design resolution).

Why it's only a Suggestion: it does not cause incorrect teardown. The two reachable elements
(`persona`, `budgets`) gate correctly (skipped when no personas, destroyed when present), and the
inline-deployed persona dashboard is torn down with the `persona` stack — no FR-9.5 orphan gap
(lead already verified the settled tree green). The only cost is reader confusion (implies a stack
type that `DESTROYABLE_STACKS` contradicts). Recommended fix: drop `"persona-dashboard"` from the
tuple → `if stack in ("persona", "budgets") and not getattr(profile, "personas", [])`. Trivial,
no behavior change, no test impact. Defer to review-1/lead since destroy.py is review-1's scope.

### Verdict: PASS
Reason: Zero criticals, zero warnings. D3 legacy enforcement preserved byte-for-byte; R-highest
3-ARN-shape Deny fully closed (policy + boundary); otel-collector closes the empty-dashboard gap in
both config blocks + EMF dimension; cfn-lint clean vs baseline (only pre-existing allowlisted
W3002); partition/namespace/cfn-naming invariants met for all new resources. Behavioral caveats
(quota_monitor empty-groups; destroy.py dead persona-dashboard tuple entry) are both pre-existing /
non-behavioral and recorded as Suggestions — neither blocks. The destroy.py item is in review-1's
scope and deferred to them for cleanup.
