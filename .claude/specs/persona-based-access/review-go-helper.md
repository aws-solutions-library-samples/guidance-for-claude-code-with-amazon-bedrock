# Review — Scope: `go-helper`

> Sole author: `review-2`. Lead consolidates per-scope verdicts (any FAIL ⇒ group FAILs).

## Cycle 1 — 2026-06-16
Reviewing: Persona-Based Access — Go credential helper + otel [scope: go-helper]

Files reviewed (working-tree state, diffed against HEAD):
- `source/go/cmd/credential-process/main.go` (+ `main_test.go`, new)
- `source/go/cmd/otel-helper/main.go` (+ `main_test.go` schema-fixture bump)
- `source/go/internal/config/config.go` (+ `personas_test.go`, new)
- `source/go/internal/jwt/decode.go` (+ `decode_test.go`)
- `source/go/internal/persona/resolve.go` (+ `resolve_test.go`, new)
- `source/go/internal/otel/extract.go`, `headers.go`, `cache.go` (+ `persona_header_test.go`, new)
- `source/go/go.sum`
Cross-referenced: `source/claude_code_with_bedrock/persona_resolution.py`, `source/tests/fixtures/persona_resolution_cases.json`, `source/tests/test_persona_parity.py`, `source/claude_code_with_bedrock/config.py` (Python `Profile`).

### Spec Alignment
- **§4.2 PersonaConfig (FROZEN) — exact match.** All 9 Go struct JSON tags are byte-identical to the frozen contract: `name`, `display_name,omitempty`, `group`, `allowed_models,omitempty`, `denied_models,omitempty`, `role_arn`, `monthly_token_limit,omitempty`, `enforcement_mode,omitempty`, `cost_tags,omitempty`. The three `ProfileConfig` additions (`personas,omitempty`, `groups_claim_name,omitempty`, `fallback_persona,omitempty`) match. Python `Profile` emits the same snake_case keys (`config.py:118-120`). §4.2 deliberately omits `daily_token_limit`/`budget_amount_usd` — those are deploy/budget-side fields the helper never reads; not a parity break.
- **§4.3 resolution (FROZEN) — exact match.** `persona.Resolve` (resolve.go:32-56) implements declared-order precedence (first persona whose `Group` ∈ user groups wins), fallback only on no-match, unknown-fallback-name → nil, empty/no-match → nil. Mirrors `persona_resolution.py:30-65` line-for-line. Group membership is exact string equality on both sides (case-sensitive — fixture `group_match_is_case_sensitive` asserts it).
- **Parity is genuinely cross-checked (not self-consistent).** `test_persona_parity.py` drives BOTH the Python resolver and the Go resolver (`go test ./internal/persona -run TestResolveAgainstSharedFixtures`) over the SAME 12-case fixture oracle, and FAILS (not skips) if the Go toolchain is absent. Ran it: **38 passed**. The Go fixture test asserts `>=5` cases and the Python side asserts the same — drift in either implementation breaks the build.
- **D2 (effective_auth_type)** is a Python-side property — out of go-helper scope; noted, not assessed here.
- **D4 (otel-helper resolves persona independently)** — implemented exactly as specified: `cmd/otel-helper/main.go:121-142` loads `personas`/`groups_claim_name`/`fallback_persona` from config and calls `ExtractUserInfoWithPersona`, which calls the same `persona.Resolve`. No cross-binary cache handshake. Empty personas → `info.Persona` stays "" → `x-persona` omitted.
- **Converse action-set decision (KNOWN-ACCEPTED)** — N/A to this scope. The Go helper performs pure role *selection*; it never emits IAM policy actions. Model Allow/Deny enforcement lives in the rendered CFN (`persona_template.py`, review-1's scope), and the helper correctly relies on the STS trust policy as the authoritative server-side gate (FR-3.2). No model-access path is decided in Go.

### Critical
None.

### Warning
None.

### Suggestion
- [`source/go/cmd/credential-process/main.go:581-585`] The hard-deny error message reads "no fallback persona is configured" for BOTH `Resolve`-returns-nil cases — (a) no fallback set, and (b) fallback set but names an unknown persona (§4.3 rule 2). The *behavior* is correct and identical (both hard-deny, which is the security requirement), so this is cosmetic. Mitigated upstream: `persona_validation.py` (review-1 scope) validates `fallback_persona` names an existing persona at config time, so case (b) is caught before it reaches the helper. Optional polish: branch the message on `cfg.FallbackPersona != ""`. Low severity — does not block. [via `feature-dev:code-reviewer`, severity-adjusted]

### Cross-Task Consistency
- **§4.2/§4.3 contract (Scope 1 Python ↔ Scope 2 Go ↔ Scope 4 parity test):** Verified consistent. Go struct ↔ Python `Profile` fields ↔ fixture oracle all agree; the parity test enforces it in CI. Coordinating with review-1 (python) and review-4 (parity) — no discrepancy found on the Go side.
- **x-persona (Scope 2 emit ↔ Scope 3 collector/dashboard):** Go side emits header `x-persona: <name>` via `HeaderMapping["persona"]="x-persona"` (headers.go:16) and the attrs map (headers.go:34), omitted when empty. The collector `x-persona`→`persona` dimension mapping and dashboard consumption are Scope 3 (review-3) — the emit side is correct and contract-stable here.
- **`buildSessionName` UNCHANGED (#204):** `sts.go` is byte-identical to HEAD (empty `git diff`). Claim priority email→sub→`claude-code`, sanitization regex `[^\w+=,.@-]`→`-`, and length limits (email 64 / sub 32) all intact. `TestBuildSessionName` (8 subtests) PASS; `test_persona_parity.py::TestBuildSessionNameUnchanged` shells the federation SessionName tests and requires exit 0 — green.

### Invariant checks (rules/)
- **credential-recursion.md** — PASS. `selectRoleARN` (main.go:565-595) is pure in-memory: reads config + claims, calls `persona.Resolve` (stdlib-only `internal/persona`, no SDK import). The only AWS call remains the existing STS `AssumeRoleWithWebIdentity` in the caller (`getAWSCredentials`). No boto3/SDK credential-resolving call introduced. `internal/persona` deliberately lives outside the SDK-linked binary (decisions.md 2026-06-15).
- **Empty-personas backward-compat** — PASS. `selectRoleARN` returns `cfg.FederatedRoleARN` unchanged when `len(cfg.Personas)==0` (main.go:566-568). The `getAWSCredentials` diff confirms the ONLY behavioral change is `FederatedRoleARN` → `selectRoleARN(...)`; the Cognito `else` branch is untouched (personas are direct-IAM only). `TestSelectRoleARN` covers `no personas → FederatedRoleARN` and `nil personas with groups present → still FederatedRoleARN`. `TestPersonaFieldsAbsentRoundTrip` confirms a legacy config.json decodes with nil persona state and re-marshals with NO persona keys (omitempty correct, no `"personas":null`).
- **No-match hard-deny** — PASS. No persona + no fallback → `selectRoleARN` returns a clear, actionable error (never a broad role). Covered by `TestSelectRoleARN` cases `no match + no fallback → hard-deny error` and `missing groups claim + no fallback → error`. Matched-persona-with-empty-RoleARN also errors clearly (re-run `ccwb package`).
- **otel-attribution-chain.md** — PASS. `x-user-email` always present: `ExtractUserInfoWithPersona` wraps `ExtractUserInfoWithTagKey`, which forces `info.Email = "unknown@example.com"` when absent; the `emitEmptyHeaders` path is untouched. `x-persona` empty-excluded: `FormatHeaders` skips empty values, and `info.Persona` is left "" on no-match (`TestFormatHeaders_PersonaEmptyExcluded`, `TestExtractUserInfoWithPersona_NoMatchLeavesEmpty`). Empty-headers cache TTL = 120s ≤ 300s (compliant). Persona `Resolve` errors are non-fatal for telemetry (correct — telemetry must not crash on a malformed claim).
- **Cache schema bump 2→3** — PASS. `currentCacheSchemaVersion = 3` (cache.go:20) with documented rationale (`v3 adds x-persona`). `ReadCachedHeaders` discards `SchemaVersion < 3` so upgraded binaries re-extract. The `cmd/otel-helper/main_test.go` Layer-1 fixtures were correctly bumped 2→3 (required — they would fail otherwise).
- **binary-distribution.md (cold-start)** — PASS. No new runtime dependencies: the sole `go.sum` change adds the `h1:` checksum line for the pre-existing test-only indirect dep `github.com/kr/pty v1.1.1` (checksum-completeness from `go mod download`, not a new import). `GetStringSlice` is stdlib-only. `internal/persona` imports only `internal/config`. Persona resolution is O(N) in-memory.
- **iam-actions.md / azure / keyring** — N/A to role-selection logic; no IAM-action strings or keyring changes in scope.

### Tests
- [x] All tests passing — full Go suite `go test ./... -count=1`: all packages OK (run twice, no flakiness). In-scope: `credential-process`, `otel-helper`, `persona`, `otel`, `jwt`, `config`, `federation` all OK. Python parity `test_persona_parity.py` + `test_persona_resolution.py`: 38 passed.
- [x] Test coverage adequate — `TestSelectRoleARN` (11 cases: backward-compat, persona match, declared-order, no-match deny, fallback, match-beats-fallback, custom claim, scalar claim, missing claim, empty-RoleARN); `TestResolveTable` (10 cases) + `TestResolveAgainstSharedFixtures` (12 fixtures); `GetStringSlice` (array/scalar/missing/empty/non-string-skipped/wrong-type/end-to-end); otel persona-header (match/declared-order/no-match/fallback/custom-claim/no-personas/empty-exclude); config round-trip (absent + populated + empty-slice-omitted). `buildSessionName` parity preserved.
- [x] `go vet` + `gofmt -l` clean on all changed files.

### Verdict: PASS
Reason: Zero criticals, zero warnings. §4.2/§4.3 frozen contracts match Python exactly and are CI-enforced by a genuine cross-language parity test; `buildSessionName` is byte-unchanged with green parity tests; empty-personas path is byte-identical backward-compat; no-match hard-denies safely; no SDK recursion; OTEL attribution chain intact (`x-user-email` always, `x-persona` empty-excluded); cache schema bump correct; no new deps. The one Suggestion (error-message wording) is cosmetic, mitigated upstream by Python-side validation, and does not block.
