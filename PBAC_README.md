# Persona-Based Access Control & Cost Governance (PBAC)

Map your OIDC groups to **personas** — named tiers that each get their own Bedrock
model allow/deny policy, token quota, cost attribution tags, and AWS Budget. PBAC
layers onto the existing `ccwb` quota + OpenTelemetry subsystem; it **reuses** that
machinery rather than rebuilding it.

> Authoritative design lives in
> [`.claude/specs/persona-based-access/spec.md`](.claude/specs/persona-based-access/spec.md)
> and [`decisions.md`](.claude/specs/persona-based-access/decisions.md). This guide
> documents **actual shipped behavior** and how to deploy and operate it. When in
> doubt, the code and CloudFormation templates are the source of truth.

---

## Contents

1. [What PBAC is (and what it reuses)](#1-what-pbac-is-and-what-it-reuses)
2. [Persona configuration schema](#2-persona-configuration-schema)
3. [⚠️ Per-IdP groups claim & the trust-condition model](#3-️-per-idp-groups-claim--the-trust-condition-model)
4. [Deploy flow & stack ordering](#4-deploy-flow--stack-ordering)
5. [⚠️ The inference-profile Deny invariant](#5-️-the-inference-profile-deny-invariant)
6. [Token tracking & enforcement](#6-token-tracking--enforcement)
7. [Cost attribution & per-persona model routing](#7-cost-attribution--per-persona-model-routing)
8. [Budgets & alerts](#8-budgets--alerts)
9. [Dashboards & queries](#9-dashboards--queries)
10. [Dynamic administration & rollback](#10-dynamic-administration--rollback)
11. [No-match / fallback behavior](#11-no-match--fallback-behavior)
12. [Auth-type & Cognito limitations](#12-auth-type--cognito-limitations)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. What PBAC is (and what it reuses)

A **persona** is a named group (matched by the OIDC `groups` claim) with five things
attached:

| Per-persona resource | What it does | How it's built |
|---|---|---|
| **IAM role** | Federated role assumed at credential-issuance time; its Bedrock policy enforces model allow/deny | Rendered into a dedicated `…-persona` CloudFormation stack |
| **GROUP quota policy** | Per-persona monthly/daily token limits | Seeded into the **existing** `QuotaPolicies` table — a persona's `group` *is* the policy identifier (no new policy type) |
| **Tagged inference profiles + model routing** | Per-persona cost attribution AND per-persona model routing | One cost-tagged Application Inference Profile per entitled tier; its ARN routes that persona's `ANTHROPIC_*_MODEL` via an opt-in launch wrapper ([§7](#7-cost-attribution--per-persona-model-routing)) |
| **AWS Budget** | Spend cap + alerts per persona (and account total) | Rendered into a `…-budgets` stack |
| **Telemetry dimension** | `persona` label on `claude_code.token.usage` for dashboards | otel-helper emits `x-persona`; the collector maps it to a metric dimension |

**PBAC reuses, it does not rebuild.** The quota subsystem (the `quota_check` and
`quota_monitor` Lambdas, the `QuotaPolicies`/`UserQuotaMetrics` tables, the
`ccwb quota` CLI) already shipped and already resolves GROUP-level policies. A persona
is just a GROUP policy whose identifier is the persona's `group` value. The OTEL
attribution chain (per-user headers → CloudWatch dimensions) is the same one used for
`department`/`team.id` today — persona adds one more dimension to it.

**v1 scope:** direct-IAM federation only. See
[§12](#12-auth-type--cognito-limitations) for Cognito and Google caveats.

---

## 2. Persona configuration schema

Personas are declared in `config.yaml` (written by `ccwb init`). Each persona is a
dict; the canonical shape (frozen contract — see
[spec §4.1](.claude/specs/persona-based-access/spec.md)):

```yaml
personas:
  - name: engineering            # identifier; DNS/IAM-safe; used in role name + policy id
    display_name: Engineering
    group: eng-team              # the value the OIDC `groups` claim must contain
    allowed_models:              # model-id globs; [] or ["*"] = all anthropic
      - "anthropic.*"
    denied_models: []            # explicit-deny globs (restricted personas)
    monthly_token_limit: 300000000
    daily_token_limit: null      # null = none
    enforcement_mode: block      # alert | block
    budget_amount_usd: null      # null = no per-persona budget
    cost_tags: {Team: Engineering}

# top-level siblings of `personas:`
groups_claim_name: groups        # the JWT claim that carries group membership (per IdP)
fallback_persona: null           # name of a persona, or null = hard-deny on no match
account_budget_amount_usd: null  # null = no account-total budget
```

| Field | Meaning | Notes |
|---|---|---|
| `name` | Persona identifier | DNS/IAM-safe (`^[A-Za-z0-9][A-Za-z0-9-]*$`); becomes the role-name stem + quota policy id. Two distinct names that sanitize to the same CloudFormation logical id (e.g. `eng-team` vs `eng_team` → `EngTeam`) are rejected by `validate_personas` |
| `group` | Group value the JWT `groups` claim must contain | This is the GROUP quota policy identifier |
| `allowed_models` | Allow globs | `[]` or `["*"]` ⇒ all `anthropic.*` |
| `denied_models` | Explicit-deny globs | Enforced across **all three** Bedrock ARN shapes — see [§5](#5-️-the-inference-profile-deny-invariant) |
| `monthly_token_limit` / `daily_token_limit` | Quota limits | Seeded as a GROUP policy |
| `enforcement_mode` | `alert` (log only) or `block` (deny at quota-check) | |
| `budget_amount_usd` | Per-persona AWS Budget | `null` ⇒ no budget for this persona. **If set, `cost_tags` must be non-empty** — the budget is scoped by the persona's cost-allocation tag, so `validate_personas` rejects a budget without tags |
| `cost_tags` | Cost-allocation tags | Applied to the persona's inference profiles; also scopes the per-persona budget |

> **Validation.** `ccwb init` and `ccwb deploy` both run `validate_personas` over the
> persona list, so a hand-edited `config.yaml` is checked before any infra is rendered:
> unique + DNS/IAM-safe names (no logical-id collisions), non-empty `group`,
> `enforcement_mode ∈ {alert, block}`, string model globs, a `fallback_persona` that
> names a real persona, and `cost_tags` present whenever `budget_amount_usd` is set.

**Reference personas** (seeded by the wizard — `persona_defaults.py`):

| Persona | `group` | Allowed | Denied | Monthly | Mode |
|---|---|---|---|---|---|
| **engineering** | `eng-team` | `anthropic.*` | — | 300M | block |
| **sales** | `sales-team` | `anthropic.*haiku*` | `anthropic.*sonnet*`, `anthropic.*opus*` | 10M | block |

`sales` is the restricted exemplar that exercises the inference-profile Deny invariant
([§5](#5-️-the-inference-profile-deny-invariant)).

---

## 3. ⚠️ Per-IdP groups claim & the trust-condition model

> **⚠️ CRITICAL — issuer-host must match the registered OIDC provider URL EXACTLY.**
> Getting this wrong does not error at deploy time — it **silently hard-denies every
> persona user**, because the STS trust condition key never matches what the IdP emits.

Each persona role's STS trust policy gates `AssumeRoleWithWebIdentity` on a condition
keyed `<issuer_host>:<groups_claim>` (e.g. `ForAnyValue:StringEquals` on
`company.auth0.com/:groups`). The `<issuer_host>` is the auth stack's registered
OIDC-provider URL with **only the `https://` scheme stripped** — trailing slashes and
path suffixes are preserved exactly. The deployer derives this via
`_resolve_issuer_host` (`deploy.py`), which strips the scheme only and **must not**
`rstrip('/')`.

| IdP | Registered provider URL | Trust-condition issuer-host | Trailing slash? |
|---|---|---|---|
| **Auth0** | `https://company.auth0.com/` | `company.auth0.com/` | ✅ **REQUIRED** — Auth0's STS condition key keeps it |
| **Azure (Entra ID)** | `https://login.microsoftonline.com/<tenant>/v2.0` | `login.microsoftonline.com/<tenant>/v2.0` | ❌ no slash, but **keeps `/v2.0`** |
| **Okta** | `https://company.okta.com` | `company.okta.com` | ❌ bare domain — the IAM OIDC provider is registered at `https://${OktaDomain}`, **not** the `/oauth2/default` token-validation issuer |
| **Generic** (Keycloak, PingFederate, **Teleport**, …) | `${oidc_issuer_url}` (you supply it with its own `https://`) | `oidc_issuer_url` scheme-stripped (e.g. `sso.company.com/realms/prod`) | ⚠️ derived from the **`oidc_issuer_url`** field (the registered provider URL), **not** `provider_domain` — and it keeps any path (e.g. a realm path). These are distinct config fields; they must agree with the registered provider URL |
| **Cognito** | n/a in v1 | — | persona provisioning is skipped ([§12](#12-auth-type--cognito-limitations)) |

This matches the issuer-URL rules in
[`.claude/rules/issuer-url-format.md`](.claude/rules/issuer-url-format.md). If users
are denied, [§13](#13-troubleshooting) starts with the slash check.

**The `groups` claim is per-IdP.** `groups_claim_name` defaults to `groups` but must
name whatever claim your IdP emits group membership in (e.g. `groups`, `roles`). Your
IdP must be configured to **emit that claim in the token** for federated (direct-IAM)
sign-in:

- **Okta / Auth0 / Entra ID / generic OIDC**: add a groups/roles claim to the token —
  see the per-provider guides under
  [`assets/docs/providers/`](assets/docs/providers/).
- **Google**: has **no native `groups` claim**; personas under Google require
  IdP-side custom group attributes. Documented caveat, not a code path we provide.

---

## 4. Deploy flow & stack ordering

PBAC slots into the normal `ccwb` lifecycle. Order matters — later stacks import
earlier stacks' outputs (see
[`.claude/rules/stack-ordering.md`](.claude/rules/stack-ordering.md)).

```text
ccwb init      # wizard writes the persona block into config.yaml
ccwb deploy    # 1. auth stack      (exports OIDCProviderArn, FederationType)
               # 2. quota stack     (QuotaPolicies / UserQuotaMetrics / quota-check API)
               # 3. persona stack    ← imports OIDCProviderArn; N× {Role + Policy [+ boundary]}
               #    └ seeds one GROUP quota policy per persona
               #    └ creates tagged Application Inference Profiles, one per persona TIER,
               #      copyFrom a cross-Region profile (idempotent); wires ARNs into config
               #    └ deploys the persona dashboard inline (at the tail of the persona step)
               # 4. budgets stack    (per-persona + account-total → budget-alerts SNS)
ccwb package --go  # writes config.json with each persona's resolved role_arn (read from
               #     stack outputs) and builds the Go credential-process (REQUIRED — see below)
ccwb test      # validates the live deployment (Bedrock access, quota API, etc.)
```

> **⚠️ Personas require the Go credential-process — package with `--go`.** Persona access
> control is enforced *entirely* by the Go credential-process: it resolves the persona
> from the OIDC `groups` claim and assumes that persona's restricted role. The legacy
> (PyInstaller/Nuitka) binary has **no persona logic** — it always assumes the base
> `FederatedRoleARN`. Packaging a persona profile without `--go` would silently ship a
> bundle where every restricted persona receives the broad base role, bypassing the
> per-persona model restrictions. `ccwb package` therefore **refuses to build** a persona
> profile without `--go` (and warns on `--regenerate-installers`).

The whole persona block is gated on **OIDC auth + at least one persona configured**.
With no personas, deploy behaves exactly as before (the credential helper uses the
single `FederatedRoleARN`).

**Cognito is detected and skipped.** Before importing `OIDCProviderArn`, the deployer
reads the auth stack's `FederationType` export; if it is `cognito`, persona
provisioning is skipped with a clear message (Cognito uses role-mapping, not the
`groups` STS trust condition v1 relies on). See
[§12](#12-auth-type--cognito-limitations).

`ccwb destroy` tears the persona resources back down in reverse-dependency order
(budgets → persona dashboard → persona stack → … → auth last), and best-effort deletes
the inference profiles (created via API, outside the CFN stack).

---

## 5. ⚠️ The inference-profile Deny invariant

> **⚠️ A restricted persona's Deny MUST span all three Bedrock ARN shapes, or it is
> trivially bypassable.** This is the single highest-risk property of PBAC (FR-2.3 /
> spec decision **D8**).

Bedrock can be invoked through three different resource ARN shapes:

| ARN shape | Example |
|---|---|
| `foundation-model/*` | `…:foundation-model/anthropic.claude-sonnet-4-…` |
| `inference-profile/*` | `…:inference-profile/us.anthropic.claude-sonnet-4-…` |
| `application-inference-profile/*` | `…:application-inference-profile/<id>` |

A Deny that covers only `foundation-model/*` is **bypassable**: a user could invoke the
same denied model through a cross-region **inference profile** ARN and the Deny would
never match. The persona policy renderer therefore emits each denied-model glob against
**all three** shapes (`persona_template.py`). The regression test
`source/tests/test_persona_policy_bypass.py` asserts the rendered `sales` policy denies
a Sonnet ARN across all three shapes (including an **inference-profile** ARN, not merely
a foundation-model one) — a foundation-model-only Deny fails that test by design.

> **Deny globs are version-normalized.** Bedrock model ids carry a version suffix
> (`…-v1:0`). The renderer appends a trailing `*` to any `denied_models` glob that lacks
> one, so a version-pinned entry like `anthropic.claude-opus-4-7` still denies the real
> `…claude-opus-4-7-v1:0` id (it would otherwise under-match on the inference-profile
> shapes). This applies to **denied** globs only — a Deny is subtractive, so widening its
> match is always safe; `allowed_models` globs are never widened. The reference personas
> already use `anthropic.*opus*`-style globs and are unaffected.

> **Global cross-Region inference (CRIS).** `global.anthropic.*` models are invoked
> against a *region-less* foundation-model ARN (`arn:<part>:bedrock:::foundation-model/…`)
> with `aws:RequestedRegion = "unspecified"`, which the regional Allow's region condition
> never matches. The renderer therefore emits a second region-less Allow
> (`AllowBedrockInvokeAllowedModelsGlobal`, scoped to the persona's *allowed* models) —
> mirroring the `AllowBedrockInvokeGlobal` statement in the shipped `bedrock-auth-*.yaml`
> templates — so personas are not strictly more restrictive than the base role on the
> global path. The restricted Deny is **also** emitted against the region-less shape, so a
> denied model stays denied whether invoked regionally or globally.

> **Note on actions:** persona policies Allow/Deny `bedrock:InvokeModel`,
> `bedrock:InvokeModelWithResponseStream`, and `bedrock:CallWithBearerToken` — the same
> action set the shipped `bedrock-auth-*.yaml` templates use. The Bedrock **Converse**
> API is authorized under `bedrock:InvokeModel` (there is no separate runtime IAM
> action), so a Deny on `InvokeModel` for a model's ARNs also blocks Converse to that
> model. See [`decisions.md`](.claude/specs/persona-based-access/decisions.md).

All Bedrock IAM actions use the `bedrock:` namespace (never `bedrock-runtime:`) — see
[`.claude/rules/iam-actions.md`](.claude/rules/iam-actions.md).

> **Other grants on a persona role.** Beyond invoke/deny, each persona role also gets
> read-only Bedrock **discovery** (`ListFoundationModels`, `GetFoundationModel`,
> `ListInferenceProfiles`, `GetInferenceProfile`) so the client can enumerate models, and
> a **namespaced `cloudwatch:PutMetricData`** scoped by a `cloudwatch:namespace`
> condition to `ClaudeCode/Bedrock/Usage` + `AWS/Bedrock` (for usage telemetry). A
> restricted persona additionally carries a **permission boundary** that caps the role to
> the same allowed-model set (so the Deny can't be widened by a later policy edit) — roll
> back BOTH the access policy and the boundary if you revert a restricted persona's model
> access. Persona roles use a fixed **`MaxSessionDuration` of 12h** (43200s), independent
> of the profile's `max_session_duration`.

---

## 6. Token tracking & enforcement

PBAC reuses the existing quota pipeline end-to-end:

- **Tracking** — `otel-helper` emits per-request telemetry; the OTEL collector writes
  `claude_code.token.usage` to CloudWatch, and `quota_monitor` aggregates per-user
  usage into `UserQuotaMetrics`.
- **Enforcement** — at credential issuance, the helper calls the quota-check API; if the
  user's effective policy is over limit and `enforcement_mode: block`, the request is
  denied. `alert` mode logs/raises alerts but always allows.
- **Per-persona alerting** — the scheduled `quota_monitor` has no JWT, so it can't see a
  user's `groups` directly. To still evaluate **per-persona alert thresholds**, the
  quota-check API persists each user's groups (`USER#<email>` / `GROUPS`, 90-day TTL) at
  issuance time, and the monitor reads that record to resolve the user's persona. Both
  enforcement (quota-check) and alerting (quota-monitor) therefore honor per-persona
  limits; a user the monitor has never seen a check for yet resolves to the default tier
  until their next credential issuance populates the record. This group-persistence write
  happens **only when `PERSONA_ORDER` is set _and_ fine-grained quotas are enabled**
  (`ENABLE_FINEGRAINED_QUOTAS=true`) — the only configuration in which the monitor actually
  reads the record. Outside that (legacy mode, or fine-grained quotas off) the monitor never
  reads it, so the write is skipped entirely and no DynamoDB traffic is wasted.

**`PERSONA_ORDER` flips group resolution from most-restrictive to declared order.**

| Mode | Trigger | Group-policy resolution |
|---|---|---|
| **Legacy** | `PERSONA_ORDER` unset/empty | Most-restrictive wins (lowest `monthly_token_limit`) — *unchanged from before PBAC* |
| **PBAC** | `PERSONA_ORDER` set (comma-joined persona `group` values, in declared order) | **First** declared group the user belongs to wins (declared-order precedence), mirroring the credential helper's persona resolver |

`deploy.py` computes `PERSONA_ORDER` from the persona list (declared order) and passes
it to the quota stack, which sets it on **both** Lambdas. If it is empty (no personas),
the Lambdas keep legacy semantics byte-for-byte — non-PBAC deployments are unaffected.

> **PBAC mode is the sole group authority.** When `PERSONA_ORDER` is set, a user whose
> groups match **none** of the declared personas falls through to the **default** quota
> tier — it does *not* revert to most-restrictive over their other groups. This matches
> the helper's no-match behavior ([§11](#11-no-match--fallback-behavior)). See
> [`decisions.md`](.claude/specs/persona-based-access/decisions.md) ("PERSONA_ORDER is
> the sole group authority").

**Fail-open vs fail-closed** is governed by the existing quota Lambda env vars
(`MISSING_EMAIL_ENFORCEMENT`, `ERROR_HANDLING_MODE`) — default fail-closed (deny) for
security. PBAC does not change those defaults.

---

## 7. Cost attribution & per-persona model routing

Cost attribution has two complementary layers.

### 7a. Tagged Application Inference Profiles + per-persona routing (FR-5.1)

`ccwb deploy` creates one **tagged Application Inference Profile (AIP) per entitled
tier** for each persona — `{pool}-{persona}-{tier}` (e.g. `pool-sales-haiku`). A
persona's entitled tiers are derived from its `allowed_models` / `denied_models`
(sales = haiku only; engineering = haiku+sonnet+opus). Each AIP carries the persona's
`cost_tags` (plus `Persona` and `Tier` tags), so Bedrock spend rolls up per persona
**and** per tier in Cost Explorer / CUR once you activate those tags as cost-allocation
tags in the Billing console.

> **⚠️ AIPs are created from a cross-Region (system-defined) inference profile**, not a
> single-Region foundation model — AWS requires a CRIS `modelSource` to produce a
> multi-Region AIP, and Claude Code routes cross-Region. The source ARN is
> partition-aware (`aws` / `aws-us-gov`).

**Routing.** Each AIP's ARN is wired back into the persona block of `config.json`
(`inference_profile_arns: {tier: arn}`) at deploy time, then serialized by
`ccwb package`. Because the persona a user belongs to is only known **at credential
issuance** (from the `groups` claim) — while `settings.json`'s `ANTHROPIC_MODEL` is
static per bundle — per-user routing is delivered by an **opt-in launch wrapper**:

- `ccwb package` emits `persona-model.sh` (POSIX) and `persona-model.ps1` (Windows)
  into the bundle **when at least one persona has resolved AIP ARNs**, and the
  generated installer (`install.sh` / `install.bat`) copies it to
  `~/claude-code-with-bedrock/` alongside the credential-process binary — so the
  `source`/dot-source path below exists after a standard install. (`ccwb package
  --regenerate-installers` re-emits it too.)
- The wrapper calls `credential-process --get-persona-model`, which resolves the user's
  persona from the cached token's `groups` claim and prints `export ANTHROPIC_*_MODEL=…`
  lines pointing at that persona's per-tier AIP ARNs — concretely
  `ANTHROPIC_DEFAULT_HAIKU_MODEL` / `ANTHROPIC_DEFAULT_SONNET_MODEL` /
  `ANTHROPIC_DEFAULT_OPUS_MODEL`, plus bare `ANTHROPIC_MODEL` = the persona's
  most-capable entitled tier. The wrapper applies them, then launches Claude.
- **Opt-in:** add the wrapper to your shell startup (the installer prints the exact
  line). `settings.json`'s baked model is unchanged, so a user who doesn't source the
  wrapper — or who matches no persona, or whose token expired — simply keeps the
  default model (no breakage).

```bash
# POSIX — add to ~/.bashrc or ~/.zshrc:
source "$HOME/claude-code-with-bedrock/persona-model.sh"
```
```powershell
# Windows — add to your PowerShell $PROFILE:
. "$env:USERPROFILE\claude-code-with-bedrock\persona-model.ps1"
```

`credential-process --get-persona-model` is local-only (no network) and exits non-zero
when there's nothing to route, so it's safe to call on every launch. Use
`--tier {haiku|sonnet|opus}` to emit a single tier.

### 7b. IAM principal-based attribution (zero-infra complement)

The STS `RoleSessionName` continues to carry user identity into
`line_item_iam_principal` (unchanged — `buildSessionName` was not touched), so per-user
attribution still works alongside per-persona attribution. The persona role ARN itself
also appears in CUR, giving per-persona rollup even without the AIP tags.

---

## 8. Budgets & alerts

`ccwb deploy` renders a dedicated **budgets stack**:

- **Per-persona budgets** — one `AWS::Budgets::Budget` per persona that sets
  `budget_amount_usd`, filtered to that persona's cost-allocation tag.
- **Account-total budget** — optional, from top-level `account_budget_amount_usd`.
- Every budget fires at **50% / 80% / 100% actual** plus **100% forecast**.

All budget alerts publish to a **dedicated** `…-budget-alerts` SNS topic — separate
from the quota-alerts topic (decision **D7**: finance and engineering audiences are
distinct). The topic policy grants `budgets.amazonaws.com` publish rights gated by an
`aws:SourceAccount` condition (confused-deputy guard).

---

## 9. Dashboards & queries

- **`ClaudeCodePersonasDashboard`** — a separate CloudWatch dashboard (deployed inline
  with the persona stack) with per-persona token usage (totals, over-time, daily rate,
  by-type), per-persona cost, active-users-by-persona, and a top-user leaderboard (by
  tokens and by cost).
- **Logs Insights queries** — per-persona QueryDefinitions appended to
  `logs-insights-queries.yaml` (Token Usage by Persona, …Over Time, Cost by Persona,
  Top Users by Persona). Unmatched datapoints surface as `(none)`.

> **Requires the collector persona dimension.** The dashboard and queries group by the
> `persona` metric label, which only exists because `otel-collector.yaml` maps the
> `x-persona` header to a `persona` attribute and adds `[[persona, OTelLib]]` to its EMF
> metric declarations. Without that wiring the widgets render **empty** even though the
> header is being emitted. (This is shipped — noting it so an operator who strips the
> collector config knows why persona widgets would go blank.)

---

## 10. Dynamic administration & rollback

| Task | How |
|---|---|
| **Change a persona's token limit** at runtime | `ccwb quota set-group <group> …` — updates the GROUP policy in DynamoDB; no redeploy needed (a persona's `group` *is* the policy id) |
| **Change a persona's model access** | Edit `allowed_models`/`denied_models` in `config.yaml`, re-run `ccwb deploy`; the persona ManagedPolicy is versioned by IAM (rollback = restore the prior policy version) |
| **Emergency disable a persona** | Disable its GROUP quota policy (block via quota) and/or detach/restrict the persona role's policy; for a hard cut, remove the group from the user in your IdP |
| **Remove a persona** | Delete it from `config.yaml` and re-run `ccwb deploy`. The persona's **IAM role is pruned** by CloudFormation (it lives in the rendered stack). Its **per-tier inference profiles** and **GROUP quota policy** are NOT auto-removed (deploy won't implicitly delete billing/quota resources) — `ccwb deploy` prints the orphaned inference-profiles' manual `aws bedrock delete-inference-profile` commands (one per `{pool}-{persona}-{tier}`), and you remove the stale group limit with `ccwb quota delete group <group>`. `ccwb destroy` cleans them up automatically. |
| **Roll back a bad deploy** | CloudFormation stack rollback for the persona/budgets stacks; IAM ManagedPolicy versioning for policy-only changes |

---

## 11. No-match / fallback behavior

When a user's `groups` claim matches **no** persona:

| `fallback_persona` | Credential helper (model access) | Quota Lambdas (token limit) |
|---|---|---|
| set to a persona name | assume that persona's role | fall through to the **default** quota tier |
| `null` (default) | **hard-deny** — exit non-zero, no role assumed | fall through to the **default** quota tier |

Default is **hard-deny** at the credential helper (no persona ⇒ no Bedrock access),
which is the secure default. Set `fallback_persona` to a low-privilege persona (e.g. a
read-mostly tier) if you prefer graceful degradation over denial.

> **Fallback applies to model access, not the quota tier.** `fallback_persona` is honored
> only by the credential helper and otel-helper (which assume/attribute the fallback
> persona). The quota Lambdas do **not** apply `fallback_persona`: they match the user's
> *actual* groups against the declared order and, on no match, use the **account default
> quota** — never the fallback persona's token limit. So a fallback user gets the fallback
> persona's *models* but the *default* monthly/daily limit. If you need the fallback tier's
> limit enforced too, set a `default` quota policy (`ccwb quota set-default`) to the value
> you want unmatched users held to.

The **match step** (declared-order precedence, exact group equality) is identical across
the Go helper, both quota Lambdas, and otel-helper. The **no-match step** differs by
design: the helper/otel-helper apply `fallback_persona` then hard-deny/none, while the
Lambdas apply the default quota tier (see
[spec §4.3](.claude/specs/persona-based-access/spec.md), which records this as-shipped).

---

## 12. Auth-type & Cognito limitations

| Auth type | Personas supported? | Why |
|---|---|---|
| **OIDC (direct-IAM)** — Okta, Auth0, Entra ID, generic | ✅ Yes | The `groups` STS trust condition requires direct-IAM federation |
| **Cognito User Pool** | ❌ Skipped in v1 | Cognito uses identity-pool role-mapping, not the `groups` web-identity trust condition; deploy detects `FederationType: cognito` and skips persona provisioning with a message (FR-2.7) |
| **IAM Identity Center (`idc`)** | ❌ No | No JWT `groups` claim; quota/persona features require OIDC |
| **`none`** | ❌ No | No federation/JWT |

- **Google** is direct-IAM but has no native `groups` claim — see
  [§3](#3-️-per-idp-groups-claim--the-trust-condition-model).
- PBAC is gated on `effective_auth_type == "oidc"`; for any other auth type the persona
  block is skipped cleanly (no crash). See
  [`.claude/rules/quota-requires-oidc.md`](.claude/rules/quota-requires-oidc.md) and
  [`auth-type-compat.md`](.claude/rules/auth-type-compat.md).

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| **All my Auth0 users are denied** (no role assumed) | Issuer-host trailing-slash mismatch — the persona trust condition keys on `company.auth0.com/` but is being emitted without the slash (or vice-versa) | Confirm the auth stack's registered provider URL keeps its trailing slash and that `_resolve_issuer_host` strips only the scheme. See [§3](#3-️-per-idp-groups-claim--the-trust-condition-model). |
| **All my Azure users are denied** | Issuer-host missing the `/v2.0` suffix | The issuer-host must be `login.microsoftonline.com/<tenant>/v2.0` (no trailing slash, but **with** `/v2.0`). |
| **All my generic/Teleport/Keycloak users are denied** | Trust-condition issuer-host derived from `provider_domain` instead of `oidc_issuer_url`, so it doesn't match the registered provider URL (esp. when the issuer has a realm path) | Confirm `oidc_issuer_url` in `config.yaml` equals the registered OIDC provider URL exactly; the issuer-host is `oidc_issuer_url` scheme-stripped (path preserved). See [§3](#3-️-per-idp-groups-claim--the-trust-condition-model). |
| **A denied model still works for a restricted persona** | Deny doesn't cover all three ARN shapes (or the user invoked it via an inference profile) | This shouldn't happen with the shipped renderer (it emits the Deny across all three shapes, guarded by `tests/test_persona_policy_bypass.py`). Inspect the deployed persona role's ManagedPolicy and confirm the denied-model globs appear against `inference-profile/*` and `application-inference-profile/*`, not just `foundation-model/*`. See [§5](#5-️-the-inference-profile-deny-invariant). |
| **Persona dashboard / queries are empty** | Collector persona dimension missing | Verify `otel-collector.yaml` maps `x-persona`→`persona` and declares the `persona` dimension. See [§9](#9-dashboards--queries). |
| **Quota limits ignore my declared persona order** | `PERSONA_ORDER` not set on the Lambdas (deploy didn't pass it, or personas not configured) | Confirm `ccwb deploy` ran with personas configured; check the `PersonaOrder`/`PERSONA_ORDER` value on both quota functions. See [§6](#6-token-tracking--enforcement). |
| **A user in no persona group can't use Bedrock at all** | `fallback_persona` is `null` (hard-deny default) | Set `fallback_persona` to a low-privilege persona if graceful degradation is wanted. See [§11](#11-no-match--fallback-behavior). |
| **Per-persona model routing isn't taking effect** | The launch wrapper isn't sourced, the persona has no resolved AIP ARNs, or no persona matched | Confirm `persona-model.sh`/`.ps1` is sourced from your shell rc; check `config.json`'s persona block has `inference_profile_arns`; run `credential-process --profile <p> --get-persona-model` directly (exit 0 = exports printed, 2 = no persona/ARNs, 4 = token expired). See [§7a](#7a-tagged-application-inference-profiles--per-persona-routing-fr-51). |
| **Personas didn't deploy at all** | Auth type is Cognito/IDC/none, or no personas configured | Personas require OIDC direct-IAM + at least one persona. See [§12](#12-auth-type--cognito-limitations). |
| **`ccwb package` refuses with "Persona-based access control requires the Go credential-process"** | You packaged a persona profile without `--go`; the legacy binary can't enforce personas | Re-run `ccwb package --go`. This guard is intentional — a legacy binary would silently grant every user the base role. See [§4](#4-deploy-flow--stack-ordering). |
| **A restricted persona can't use a `global.*` model** | (Pre-fix symptom.) The renderer now emits a region-less global-CRIS Allow scoped to allowed models. | Confirm the deployed persona policy has an `AllowBedrockInvokeAllowedModelsGlobal` statement; redeploy if it's an older stack. Denied models stay denied on the global path. See [§5](#5-️-the-inference-profile-deny-invariant). |

---

## Related documentation

- [Spec](.claude/specs/persona-based-access/spec.md) · [Design](.claude/specs/persona-based-access/design.md) · [Decisions](.claude/specs/persona-based-access/decisions.md)
- [Monitoring Guide](assets/docs/MONITORING.md) · [Quota Monitoring](assets/docs/QUOTA_MONITORING.md)
- [Identity provider setup guides](assets/docs/providers/)
- Rules: [issuer-url-format](.claude/rules/issuer-url-format.md) · [iam-actions](.claude/rules/iam-actions.md) · [quota-requires-oidc](.claude/rules/quota-requires-oidc.md) · [stack-ordering](.claude/rules/stack-ordering.md)
