# FR-5.1 — Per-Persona Inference-Profile Model Routing (post-build addition)

> Added 2026-06-15 after the deep-dive review surfaced that FR-5.1 was only
> half-implemented: per-persona Application Inference Profiles (AIPs) were
> **created + tagged** (cost attribution works) but their ARNs were never
> **wired into model routing**. The user directed full implementation.
> Option chosen: **Full — config.json + auto-generated launch wrapper.**

## Problem

- Personas resolve **per-user at credential-issuance** (Go helper, from the OIDC
  `groups` claim). But `ANTHROPIC_MODEL` is baked **statically into
  settings.json at `package` time** — one value for all users. The two layers
  don't meet.
- The global `inference_profile_{opus,sonnet,haiku}_arn` fields are
  stored/validated/displayed but **never wired into routing either** — they are
  dead config today. So there is no existing mechanism for personas to plug into.
- The shipped per-persona AIP creation used
  `copyFrom: foundation-model/anthropic.claude-3-haiku-…` — a **single-region**
  source. AWS requires a **cross-Region (system-defined) inference profile**
  modelSource to produce a **multi-Region** AIP. A single-region AIP would break
  Claude Code's CRIS routing. (AWS docs: *inference-profiles-create* — "for
  multiple Regions, specify a cross Region (system-defined) inference profile".)

## Verified AWS mechanics (docs)

- An inference profile **ARN is accepted in place of a model ID** in `InvokeModel`
  / `Converse` `modelId` (*inference-profiles-use*). So an AIP ARN is a valid
  `ANTHROPIC_MODEL` / `ANTHROPIC_DEFAULT_*_MODEL` value.
- A multi-Region AIP must `copyFrom` a CRIS profile id (e.g. `us.anthropic.…`),
  NOT a bare `foundation-model/…`.

## Design (as built)

### 1. AIP creation reworked (deploy.py `_create_persona_inference_profiles`)
- For each persona, create **one AIP per entitled tier** the persona can invoke
  (derived from `allowed_models` vs `denied_models`; default all three tiers).
  Name: `{pool}-{persona}-{tier}`.
- `modelSource.copyFrom` = the **CRIS profile ARN** for that tier+region, built
  from `resolve_model_for_tier(tier, cross_region_profile)` →
  `arn:{partition}:bedrock:{region}::inference-profile/{cris_model_id}`.
- Partition is resolved (`aws`/`aws-us-gov`) — fixes the L-a GovCloud hardcode.
- Idempotent check-then-create by name (unchanged contract). Orphan detection
  updated for the per-tier names.
- After create (or if already-exists), **read back each AIP's ARN** and store it
  on the persona dict: `persona["inference_profile_arns"] = {tier: arn, …}`.
  Persisted to the profile so `package` serializes it.

### 2. config schema (Python Profile + Go PersonaConfig)
- Persona dict gains `inference_profile_arns: dict[str,str]` (tier→ARN), e.g.
  `{"haiku": "arn:…:application-inference-profile/…"}`.
- Go `PersonaConfig` gains `InferenceProfileArns map[string]string
  json:"inference_profile_arns,omitempty"`. (config-sync.md parity.)
- `_serialize_persona` (package.py) emits it when present.

### 3. Go credential-process — `--get-persona-model`
- New flag mode (pure-local, no network): read cached monitoring token → decode
  claims → `persona.Resolve(groups, personas, fallback)` → print the persona's
  tier ARN(s) as **shell `export` lines** (POSIX) or nothing on no-match.
- `--tier {default|haiku|sonnet|opus}` selects which env var(s) to emit. Default
  emits the full set the persona has ARNs for:
  `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `…_SONNET_MODEL`, `…_OPUS_MODEL`, and
  `ANTHROPIC_MODEL` (the persona's primary tier — highest entitled).
- Exit codes mirror `--get-tag`: 0 emitted, 2 no persona / no ARNs, 4 token
  expired. Never errors the shell (wrapper tolerates non-zero → no override).
- Reuses existing `internal/persona` + `internal/jwt` — no new deps, cold-start
  budget unaffected (binary-distribution.md).

### 4. package.py — generated launch wrapper
- Emits `persona-model.sh` (POSIX) + `persona-model.ps1` (Windows, CRLF) next to
  the binary, only when the profile has personas with inference_profile_arns.
- The wrapper runs `credential-process --profile P --get-persona-model` and
  `eval`s/Invoke-Expression its output before `claude`. Documented as opt-in
  (user adds the shim to their shell rc) — settings.json's static ANTHROPIC_MODEL
  remains the floor; the wrapper overrides per-launch when a persona matches.
- settings.json static model env unchanged (back-compat: non-persona + the
  "user not in any persona" case keep the baked default).

### 5. Docs + tests
- PBAC_README §7 rewritten: tag-based attribution PLUS the per-persona routing
  wrapper, with the CRIS-source requirement and the opt-in shim snippet (both
  shells).
- Tests: Go `--get-persona-model` table tests (match/no-match/expired/tier
  select); Python AIP-source CRIS + partition tests; serialization round-trip;
  parity (PersonaConfig field); wrapper-content tests (POSIX+PS1, CRLF).

## Backward compatibility
- No personas / no AIP ARNs → wrapper not generated, no env override, settings
  static model unchanged. Existing deployments byte-unaffected.
- Cognito federation still skips personas entirely (FR-2.7) — no AIPs, no wrapper.
