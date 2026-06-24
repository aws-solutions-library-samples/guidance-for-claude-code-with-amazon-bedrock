# Requirements — Persona-Based Access & Cost Governance

> Status: Draft for review · Slug: `persona-based-access` · Date: 2026-06-15
> Source inputs: `bedrock-migration-customer-guide.md`, `bedrock-final-architecture.png` (this directory)

## Project Summary

Extend the `ccwb` deployment system (this repo) with **persona-based model access control** and **per-persona cost governance**, layered onto the existing OIDC→IAM federation, OTEL monitoring, and quota subsystems. A *persona* is a named group of users (e.g. Engineering, Sales) with (a) a defined set of Claude models they may invoke, (b) token limits, and (c) cost-attribution tags. Persona membership is derived from an OIDC claim at authentication time; each persona maps to its own IAM role whose policy enforces model access (Allow + explicit Deny + permission boundary). Token tracking and enforcement **reuse the existing OTEL→quota pipeline and real-time quota-check API**; cost governance adds tagged Application Inference Profiles, IAM principal-based cost-allocation, and AWS Budgets (per-persona + account total).

The design is **config-driven for N personas** — Engineering and Sales from the customer guide are the reference instances, not hardcoded. The build is a **native extension of `ccwb`** (CloudFormation + Python CLI + Go credential helper), honoring the repo's Tier-1 invariants (Go↔Python config parity, `bedrock:` IAM namespace, OIDC-only quota, backward-compatible configs, OTEL attribution chain).

### What already exists (reuse — do NOT rebuild)
- One shared OIDC provider + one federated role + one `BedrockAccessPolicy` allowing **all** `anthropic.*` models (`deployment/infrastructure/bedrock-auth-*.yaml`).
- Fine-grained quota policies at **user / group / default** levels (`QuotaPolicies` table), per-user usage (`UserQuotaMetrics`), daily+monthly limits, `alert`/`block` enforcement modes, SNS alerts, EventBridge-scheduled `quota_monitor` Lambda (`quota-monitoring.yaml`).
- Real-time **quota-check HTTP API** (JWT-authorized) that the credential helper calls at credential issuance — blocks issuance when over limit; `quota_fail_mode` open/closed; `quota_check_interval` re-check cadence (the "detect + block next" mechanism).
- OTEL attribution pipeline: `otel-helper` → collector (sidecar/central) → CloudWatch metrics → `quota_monitor` → `UserQuotaMetrics`; bypass detection (CloudTrail-vs-OTEL) as a detective control.
- `Profile` already carries `inference_profile_{opus,sonnet,haiku}_arn` (consumed by the helper for model routing) and the full quota field set.
- `ccwb quota set-user|set-group|set-default|show|delete` policy-management CLI.

### What is net-new (build)
1. Persona definitions in config (claim match rule, allowed/denied models, token limits, cost tags, inference-profile ARNs).
2. Per-persona IAM roles + Bedrock policies (Allow + explicit Deny) + permission boundaries, generated for N personas.
3. Claim→role resolution in the Go credential helper (single package serves all personas; STS trust policy is the server-side gate).
4. Per-persona Application Inference Profiles (tagged) + cost-allocation tag activation.
5. AWS Budgets: one per persona (tag-filtered) + one account-total, with threshold + forecast SNS alerts.
6. Persona-aware CloudWatch dashboard with per-persona usage and a top-user leaderboard.
7. `ccwb` wizard/deploy/package/test integration for all of the above.
8. A `PBAC_README.md` (repo root) documenting deploy + use of every PBAC feature, linked from the main `README.md`.

---

## Functional Requirements

### FR-1 — Persona Model & Configuration
- **FR-1.1** Support an arbitrary number (N ≥ 1) of personas defined **declaratively in `config.yaml`** (the single source of truth). Each persona definition includes: `name` (unique, kebab/identifier-safe), `display_name`, `group` (the `groups`-claim value that confers membership — FR-1.3), `allowed_models` (list of model IDs or wildcard patterns), `denied_models` (explicit-deny list, optional), `token_limits` (`monthly`, optional `daily`, `enforcement_mode`), and `cost_tags` (e.g. `Team`, `CostCenter`, `Project`). Top-level persona config also carries a `groups_claim_name` (default `groups`; `cognito:groups` etc. per IdP) and an optional `fallback` persona name (FR-2.9). Persona **declared order** in `config.yaml` defines multi-match precedence (FR-3.3).
- **FR-1.2** Ship Engineering and Sales as **reference persona definitions** (Engineering = all Claude models; Sales = Haiku-only + explicit Deny on Sonnet/Opus) the user can keep, edit, or replace. Models are referenced **by ID/wildcard only** — no pricing data is stored in config; the guide's prices are illustrative docs (FR-6.3, OQ-7).
- **FR-1.3** Persona membership is driven by the OIDC **`groups`** claim (the standardized mechanism — `sub`-prefix matching is **not** used). A single configured group value per persona must drive **both** role assumption (trust-policy condition) and quota resolution (group policy) — both must reference the identical claim name + value so they cannot diverge. The **claim name** is configurable (providers differ: Okta/Auth0/Azure `groups`, Cognito `cognito:groups`, generic per-IdP); the **mechanism** is fixed to group membership. (See FR-2, FR-3, FR-4, Edge Cases.)
- **FR-1.4** Persona configuration must round-trip through `ccwb package` into `config.json` so the Go helper can perform claim→role resolution (Go↔Python parity — see `config-sync.md`, `credential-helper-parity.md`).
- **FR-1.5** A persona may declare which model **tiers** (opus/sonnet/haiku) it is entitled to and the inference-profile ARNs for each (per-persona, tagged — see FR-5).
- **FR-1.6** Backward compatibility: a config with **no** personas defined must behave exactly as today (single `federated_role_arn`, shared policy). No persona feature may break existing deployments (see `auth-type-compat.md`).

### FR-2 — Persona-Based Access Control (IAM)
- **FR-2.0** Persona IAM resources are delivered as a **single, dedicated CLI-rendered CloudFormation stack** (`bedrock-personas`). `ccwb` renders one role+policy+boundary block per persona at deploy time from the `config.yaml` definitions; the stack **imports the OIDC provider ARN** from the existing auth-stack export (`${AuthStackName}-OIDCProviderArn`) rather than recreating it, and the seven `bedrock-auth-*.yaml` templates remain unedited. Adding/removing a persona is a re-render + `ccwb deploy` that CloudFormation reconciles in place. CI must `cfn-lint` a representative rendered output. Deploy order: auth stack → persona stack (check the export exists; fail clearly if not — `stack-ordering.md`).
- **FR-2.1** Generate one IAM **role per persona**, each with a trust policy that permits `sts:AssumeRoleWithWebIdentity` (+ `sts:TagSession`) **only** for principals whose `groups` claim contains the persona's configured group value (e.g. `<issuer>:groups` condition matching `engineering`). Membership is by group claim (FR-1.3) — not `sub` prefix.
- **FR-2.2** Generate one **Bedrock access policy per persona**: an `Allow` for the persona's permitted models and an explicit `Deny` for excluded models. Explicit Deny is mandatory for restricted personas (deny-first defense — IAM Deny always wins).
- **FR-2.3** **Critical invariant:** model Allow/Deny statements must cover **all three ARN shapes** the runtime can invoke — `foundation-model/*`, `inference-profile/*` (system cross-region, e.g. `us.anthropic.*`), and `application-inference-profile/*`. A Deny that only names `foundation-model/anthropic.claude-sonnet-*` is ineffective because Claude Code typically invokes via a cross-region **inference profile** ARN. (The customer guide's Sales policy has this gap; we must not reproduce it.)
- **FR-2.4** Attach a **permission boundary** to restricted personas (e.g. Sales) capping maximum permissions to the persona's model set (defense-in-depth).
- **FR-2.5** All IAM actions use the `bedrock:` namespace only — never `bedrock-runtime:` (see `iam-actions.md`).
- **FR-2.6** No hardcoded resource names; derive from `!Sub '${AWS::StackName}-*'` and persona name (see `cfn-naming.md`). Templates pass `cfn-lint`.
- **FR-2.7** Persona support is **direct-IAM federation only for v1** (the six group-claim providers: Okta, Azure AD, Auth0, Google, generic/Teleport — all of which can express a `groups` STS trust condition). Under **Cognito identity-pool** federation, `ccwb` must **skip persona provisioning** with a clear message and fall back to the existing single shared role; this is a documented limitation, not a failure. Cognito role-mapping personas are explicitly deferred (see OQ-8, OOS-8). Config/persona abstractions need not pre-engineer for Cognito, but must not actively preclude a later addition.
- **FR-2.8** Persona roles reuse the existing region-scoping pattern (`aws:RequestedRegion` ∈ `AllowedBedrockRegions`) and the CloudWatch-metrics `PutMetricData` grant used by `otel-helper`.
- **FR-2.9** **No-match behavior is configurable, defaulting to hard-deny.** By default a user whose `groups` claim matches no persona assumes no role and is denied (fail-closed). The customer may optionally designate one persona as the `fallback` in `config.yaml`; when set, unmatched users resolve to it (typically a least-privilege persona). Both paths must be implemented and tested. No fallback role is created unless explicitly designated (see FR-3.3, EC-2).

### FR-3 — Claim-Based Role Resolution (Credential Helper)
- **FR-3.1** A **single** credential-helper package serves all personas. The helper reads persona definitions from `config.json`, evaluates the authenticated user's `groups` claim against each persona's configured group value, and assumes the matched persona's role ARN.
- **FR-3.2** The STS trust policy is the **authoritative server-side gate** — client-side resolution only selects which role to attempt; a tampered local config cannot escalate access because STS rejects a mismatched claim.
- **FR-3.3** Resolution is deterministic. **No match** → hard-deny with a clear diagnostic ("not a member of any provisioned persona group; contact your admin"), unless a `fallback` persona is configured, in which case resolve to it (FR-2.9). **Multiple matches** (user in several persona-mapped groups) → resolve by **declared order** in `config.yaml` (first listed wins), logged with a diagnostic so the precedence is visible; the same precedence rule must be applied identically by the quota-check Lambda (FR-4.3, EC-4). Precedence and no-match behavior are documented for admins.
- **FR-3.4** Go ↔ Python parity: persona fields added to the Go `ProfileConfig` with JSON tags identical to the Python `Profile`; claim→role logic covered by a parity test (see `credential-helper-parity.md`). No `boto3`/AWS SDK credential-resolving calls inside credential-process (`credential-recursion.md`) — Go STS direct call only.
- **FR-3.5** Persona selection must not break the OTEL attribution chain: `x-user-email` always present; if a persona/team header is emitted it follows the exclude-empty `FormatHeaders` rule (see `otel-attribution-chain.md`).
- **FR-3.6** Helper cold-start budget unaffected (<100ms target; no heavy new dependencies — see `binary-distribution.md`).

### FR-4 — Token Tracking & Enforcement (reuse OTEL + quota API)
- **FR-4.1** Reuse the existing OTEL→`UserQuotaMetrics`→`quota_monitor` pipeline and the real-time `quota-check` API. No parallel ingestion pipeline.
- **FR-4.2** Express each persona's token limits as a **group-level quota policy** (`QuotaPolicies`, `policy_type=GROUP`, identifier = persona) so existing resolution (user > group > default) applies unchanged. Seed reference persona limits at deploy time.
- **FR-4.3** The quota-check Lambda must resolve a user's persona from the **same `groups` claim** used for role assumption (FR-1.3), applying the **identical declared-order precedence and fallback** rules as the credential helper (FR-3.3) so a user's enforced limit always matches the role they actually assume. This reuses the Lambda's existing `extract_groups_from_claims` path — the persona *is* the group, so no new resolution mechanism is required, but the precedence/fallback logic must be kept in lockstep with the helper.
- **FR-4.4** Enforcement semantics: **async detect + block-next**. Over-limit is detected from telemetry; the next credential issuance / re-check (`quota_check_interval`) blocks per `enforcement_mode` (`alert` vs `block`) and `quota_fail_mode` (open/closed). The in-flight over-limit request is not killed mid-stream (matches the diagram's async design).
- **FR-4.5** Quota + persona features require OIDC. For `auth_type ∈ {idc, none}`, skip persona-claim gating and quota with a clear warning — do not fail the deploy (see `quota-requires-oidc.md`). Document the reduced-capability behavior.

### FR-5 — Cost Attribution
- **FR-5.1** Create per-persona (and per-entitled-tier) **Application Inference Profiles**, tagged with the persona's `cost_tags` (`Team`, `CostCenter`, `Project`). Wire the resulting ARNs back into config + persona definitions (FR-1.5) and into the helper's model routing.
- **FR-5.2** Activate cost-allocation tags so persona spend appears natively in Cost Explorer / CUR 2.0 (`ce update-cost-allocation-tags-status` for the persona tag keys), and document **IAM principal-based cost allocation** (role ARN appears in CUR) as the zero-infra complement.
- **FR-5.3** Inference-profile creation and tag activation are region-aware and must degrade gracefully where unsupported (see `region-availability.md`).

### FR-6 — Budgets & Alerts
- **FR-6.1** Create **one AWS Budget per persona**, filtered by the persona's cost-allocation tag, plus **one account-total** budget.
- **FR-6.2** Each budget fires at **50% / 80% / 100% actual** and a **forecasted** threshold, published to a **dedicated `claude-code-budget-alerts` SNS topic** — separate from the existing `claude-code-quota-alerts` (`QuotaAlertTopic`) so dollar-spend alerts (finance audience) and token-quota alerts (eng audience) have independent subscribers. The AWS Budgets service principal must be granted `SNS:Publish` on the new topic.
- **FR-6.3** Budget dollar amounts are set **explicitly per persona** (and for the account total) in `config.yaml` by the admin — there is **no pricing table or token×price derivation** in the product (prices change; hardcoding rots). The guide's cost figures appear only in docs as dated, illustrative examples (OQ-7).
- **FR-6.4** Budgets are net-new infrastructure (no `AWS::Budgets` exists today) delivered as CFN honoring `cfn-naming.md`; deploy ordering after persona roles/inference profiles exist (see `stack-ordering.md`).

### FR-7 — Dashboards & Visibility
- **FR-7.1** Extend the existing CloudWatch dashboard (`claude-code-dashboard.yaml`) with a **persona dimension**: per-persona token usage (daily/monthly), per-persona spend, and Allow/Deny event counts.
- **FR-7.2** Provide a **top-user leaderboard** (highest token consumers) and per-persona breakdown widgets.
- **FR-7.3** Provide Logs Insights queries (extend `logs-insights-queries.yaml`) for per-user and per-persona aggregation and cost estimation.

### FR-8 — Dynamic Administration (no redeploy)
- **FR-8.1** Change a persona's **token limits** at runtime via the existing `ccwb quota set-group <persona>` / DynamoDB write — effective on next quota check, no redeploy.
- **FR-8.2** Change a persona's **model access** at runtime via IAM policy versioning (`create-policy-version --set-as-default`) — effective immediately. Provide a `ccwb` affordance or documented procedure.
- **FR-8.3** **Emergency disable** of a persona or user: set limit to 0 / disable policy, or attach a surgical inline `Deny` — documented runbook with rollback (guide Appendix B).
- **FR-8.4** All dynamic changes must be expressible through `ccwb` commands or clearly documented AWS CLI procedures; destructive/production actions require explicit confirmation.

### FR-9 — CLI / Wizard Integration
- **FR-9.0** **No new `ccwb persona` subcommands.** Personas are managed **declaratively** through `config.yaml` (authored by the `init` wizard or edited by hand) and materialized by `ccwb deploy`; runtime token-limit tuning uses the existing `ccwb quota set-group <persona>`. `config.yaml` is the single source of truth (OQ-5). No read-only persona verbs in v1.
- **FR-9.1** `ccwb init` wizard: offer persona configuration (define personas, `groups`-claim value per persona, `groups_claim_name`, model entitlements, token limits, explicit budget amounts, optional `fallback` persona); only offer persona/quota features when auth type is OIDC and federation is direct-IAM (FR-2.7). Writes the persona block into `config.yaml`.
- **FR-9.2** `ccwb deploy`: render and deploy the dedicated `bedrock-personas` stack (FR-2.0), inference profiles, the budgets stack, and dashboard updates in dependency-correct order (auth → personas → inference profiles → budgets); check required stack outputs exist before referencing them and fail with clear messages (`stack-ordering.md`). Under Cognito federation, **skip** persona/budget provisioning with a clear message and retain the single shared role (FR-2.7).
- **FR-9.3** `ccwb package`: serialize persona definitions into `config.json` for the Go helper (FR-1.4).
- **FR-9.4** `ccwb test`: validate persona behavior — assert (a) Engineering can invoke an allowed model, (b) Sales is `AccessDenied` on Sonnet/Opus **including via inference-profile ARNs**, (c) Sales can invoke Haiku, (d) quota counter increments, (e) over-limit blocks per mode. Mirror the guide's testing gates (`iam simulate-custom-policy` + live invoke).
- **FR-9.5** `ccwb destroy`/cleanup must tear down persona roles, inference profiles, and budgets cleanly.

### FR-10 — Documentation (`PBAC_README.md`)
- **FR-10.1** The implementation must deliver, as a final artifact, a dedicated **`PBAC_README.md`** at the repository root — the single authoritative guide to deploying, configuring, and operating the Persona-Based Access Control & cost-governance features. It must cover **everything** built under these requirements (FR-1 … FR-9); a reader should be able to go from zero to a working persona deployment using only this file plus the existing `ccwb` quick-start.
- **FR-10.2** Coverage must include, at minimum: (a) overview + how PBAC layers onto the existing `ccwb` system; (b) the `config.yaml` persona schema and the Engineering/Sales reference personas; (c) per-IdP setup to emit the `groups` claim and the trust-condition model (FR-1.3, DD-1); (d) the end-to-end deploy flow and stack ordering (`init` → `deploy` → `package` → `test`, dedicated persona stack, Cognito skip behavior); (e) the inference-profile ARN gap / deny-first invariant (FR-2.3) stated as a prominent warning; (f) token tracking & enforcement (reuse of OTEL + quota-check API, alert/block modes, fail-open/closed); (g) cost attribution (tagged inference profiles, cost-allocation tags); (h) budgets & the separate SNS topic; (i) dashboards; (j) dynamic administration (limit changes, model-access versioning, emergency disable) **with rollback**; (k) no-match/fallback behavior; (l) auth-type and Cognito limitations; (m) a troubleshooting section.
- **FR-10.3** The main **`README.md`** must link to and reference `PBAC_README.md` (e.g., in a features/documentation section) so the PBAC capability is discoverable from the project entry point.
- **FR-10.4** Documentation must reflect **actual implemented behavior** (verify against the shipped code/templates, not the customer guide's aspirational text); follow the repo's `documentation` skill conventions. `PBAC_README.md` and the `README.md` edit are Tier-3 docs (`review-tiers.md`) but their accuracy is gated by the FR-9.4 `ccwb test` outcomes they describe.

---

## Non-Functional Requirements

- **NFR-1 (Parity & Tiering)** Changes touch Tier-1 files (`config.py`, `deploy.py`, `credential-process/main.go`, `internal/config/config.go`, `bedrock-auth-*.yaml`). Each changed path needs a regression test, a backward-compat test (old configs load/work), Go↔Python parity tests, and validation across auth types oidc/idc/none (see `review-tiers.md`).
- **NFR-2 (Cross-platform)** Windows tests are **blocking**. Any generated scripts use CRLF and `encoding="utf-8"`; respect Windows guards (`windows-platform-guards.md`). Helper builds for macOS arm64/x64, Linux x64, Windows x64.
- **NFR-3 (Security / least privilege)** Deny-first persona policies; permission boundaries on restricted personas; no hardcoded secrets; trust conditions validated against real IdP claim formats; production-safety confirmations for destructive admin actions.
- **NFR-4 (Performance)** Credential-helper cold start <100ms; claim→role resolution adds negligible latency; enforcement stays async (zero added latency on model invocations).
- **NFR-5 (Cost)** Reuse existing DynamoDB/Lambda/OTEL infra; new infra limited to per-persona roles/policies, inference profiles, budgets, dashboard widgets. PAY_PER_REQUEST DynamoDB retained.
- **NFR-6 (Template hygiene)** All CFN passes `cfn-lint` + `cfn_nag`; no hardcoded names; region-specific values (ELB account IDs, model/inference-profile availability) handled per `region-availability.md`.
- **NFR-7 (IdP-agnostic)** Persona matching must work across the **direct-IAM** IdPs in v1 (Okta, Azure AD, Auth0, Google, generic/Teleport); the `groups`-claim **name** is configurable because group representation differs per provider (FR-1.3). Cognito identity-pool personas are deferred (FR-2.7, OOS-8). Honor per-provider issuer URL formats (`issuer-url-format.md`).
- **NFR-8 (GovCloud)** Single codebase for commercial + GovCloud partitions (use `${AWS::Partition}`, partition-aware principals as existing templates do).
- **NFR-9 (Observability integrity)** Persona changes never produce anonymous telemetry; `x-user-email` always present; attribution chain intact (`otel-attribution-chain.md`).

---

## Edge Cases

- **EC-1** Inference-profile vs foundation-model ARN gap: a persona Deny must block the **inference-profile** form, not just `foundation-model/*`, or restriction is bypassable (FR-2.3). Test explicitly.
- **EC-2** User matches **zero** personas (claim absent or unmatched) → hard-deny by default (clear diagnostic), or the configured `fallback` persona if set (FR-2.9, FR-3.3); must not crash and must not silently grant broad access.
- **EC-3** User matches **multiple** personas → resolved by **declared order** in `config.yaml` (first wins), logged; identical rule in helper and quota-check Lambda (FR-3.3, FR-4.3).
- **EC-4** User belongs to **multiple groups** that each map to a persona (e.g. someone in both `engineering` and `sales`) → multi-match resolution per FR-3.3 must apply consistently to **both** role assumption and quota resolution, so entitled models and enforced limit stay aligned. Test divergence.
- **EC-5** Legacy config with no personas, or `sso_enabled`-only (pre-`auth_type`) config → falls back to single shared role; `effective_auth_type` used throughout.
- **EC-6** `auth_type ∈ {idc, none}` → persona claim-gating and quota unavailable; deploy proceeds with warning, no CFN failure.
- **EC-7** New Claude model released → Engineering wildcard (`anthropic.*`) auto-allows; restricted personas remain denied unless explicitly enabled (and Deny on new expensive models must be reviewed). Document the model-onboarding procedure.
- **EC-8** Cross-region inference: model invoked via `us./eu./apac.` system profile must be governed by persona policy and routed correctly per the persona's entitled region.
- **EC-9** Cognito identity-pool federation expresses authorization via identity-pool role mapping / principal tags rather than a `groups` STS trust condition → **v1 skips persona provisioning under Cognito** and keeps the single shared role (FR-2.7, OOS-8). `ccwb` must detect Cognito federation and emit the skip message rather than rendering a broken persona stack.
- **EC-10** Windows Credential Manager 1280-byte limit — large IdP tokens carrying group claims must still chunk correctly (`keyring-chunking.md`).
- **EC-11** Quota-check API fail mode under outage: `quota_fail_mode` open vs closed must be honored per persona expectation (a "block" persona should arguably fail closed).
- **EC-12** Azure tenant extraction: never pass raw `*_domain` URLs as CFN params; use the tenant-extraction helper (`azure-tenant-extraction.md`).
- **EC-13** OAuth callback robustness preserved (single-package multi-persona flow still uses the existing callback; don't shut down on first request; WSL/VPN caveats) (`oauth-callback-safety.md`).

---

## Out of Scope (v1)

- **OOS-1** Near-real-time **hard block** of an in-flight invocation (inference-path proxy/gateway). Enforcement is async detect + block-next by decision.
- **OOS-2** A second **Bedrock model-invocation-logging → subscription-filter → Lambda** enforcement pipeline. Enforcement reuses OTEL. (Optional model-invocation-logging for *audit/forensics only* may be a documented opt-in, not enforcement.)
- **OOS-3** Standalone Terraform module (guide Appendix A) — **confirmed out of scope**, not a deliverable in any phase. Build target is native `ccwb` CFN/Python only.
- **OOS-4** **All AI-DLC content — completely out of scope** (confirmed). This includes the Inception/Construction/Operation methodology, Bolts/Mob-Elaboration rituals, UNIT-* breakdown as a delivery framework, and every guide §3 Phase 3 item: AI-driven anomaly detection, capacity-recommendation automation, drift-detection bots, and operational AI playbooks. None of these are v1 features **or** documentation deliverables. Baseline alerting is limited to AWS Budgets + the existing quota SNS path + existing bypass detection.
- **OOS-5** Predictive budget **forecasting models** beyond AWS Budgets' native forecast thresholds.
- **OOS-6** Migrating users off Teleport / IdP-side configuration changes — customer-side runbook content, not product code.
- **OOS-7** Per-project (vs per-persona) cost allocation beyond tag pass-through.
- **OOS-8** **Cognito identity-pool persona support** — deferred to a future version. v1 personas are direct-IAM federation only; Cognito deployments keep the existing single shared role (FR-2.7, EC-9). Config abstractions must not preclude a later role-mapping implementation.
- **OOS-9** First-class `ccwb persona` subcommands (add/list/show/set-models). Personas are managed declaratively via `config.yaml` (FR-9.0, OQ-5).

---

## Open Questions

All product-shaping open questions are **resolved** (decisions recorded below and reflected in the FRs/OOS above). Remaining items are implementation details to settle in `design.md`, not decisions needing the user.

### Resolved decisions
- **OQ-1** Persona-role generation — **RESOLVED:** CLI-rendered **single** CFN stack (one role+policy+boundary block per persona, rendered at deploy time). See FR-2.0.
- **OQ-2** Stack location — **RESOLVED:** **dedicated** `bedrock-personas` stack importing the OIDC-provider export; the seven `bedrock-auth-*.yaml` stay unedited. See FR-2.0.
- **OQ-3** Membership claim — **RESOLVED:** the **`groups`** claim (claim *name* configurable per IdP; mechanism fixed to group membership). `sub`-prefix not used. See FR-1.3.
- **OQ-4** Budgets SNS — **RESOLVED:** a **separate `claude-code-budget-alerts`** topic, distinct from the quota topic. See FR-6.2.
- **OQ-5** Persona management — **RESOLVED:** **declarative via `config.yaml`** + existing `ccwb quota set-group`; no new persona subcommands. See FR-9.0, OOS-9.
- **OQ-6** No-match users — **RESOLVED:** **configurable, default hard-deny**; optional `fallback` persona. See FR-2.9, FR-3.3.
- **OQ-7** Models/pricing — **RESOLVED:** **fully config-driven**, explicit dollar budgets, no pricing math in product; prices are dated docs only. See FR-1.2, FR-6.3.
- **OQ-8** Cognito mode — **RESOLVED:** **direct-IAM only for v1**; Cognito skips persona provisioning. See FR-2.7, EC-9, OOS-8.

### Residual design-phase details (no user decision required)
- **DD-1** Exact trust-condition operator on `groups` per IdP (`StringEquals` vs `ForAnyValue:StringEquals`) and the per-IdP setup steps to emit a `groups` claim (Okta/Auth0/Azure/Google/generic).
- **DD-2** Concrete `config.yaml` persona schema (keys, validation, defaults) and how it serializes into `config.json` for the Go helper.
- **DD-3** CI approach for linting CLI-rendered persona templates (fixture of a representative rendered output vs render-in-CI).
- **DD-4** Whether the budgets stack is rendered alongside personas or a separate static-parameterized template, and the budget-amount config keys.
- **DD-5** Inference-profile creation idempotency/teardown semantics within `ccwb deploy`/`destroy`.

---

## Notes

- **Delivery framing.** Delivery follows the repo's own spec-driven workflow + agent-team protocol. The customer guide's AI-DLC narrative and its UNIT-*/Bolt breakdown are **explicitly out of scope** (OOS-4) and are not used as a delivery framework or task seed; `tasks.md` will be authored fresh from the FRs in this document.
- **Relationship to guide.** The guide assumes the official guidance provides observability "but not enforcement." That is **outdated for this repo** — enforcement (quota policies, block mode, quota-check API, bypass detection) already exists. This work adds the *persona/model-access* and *budgets/inference-profile* layers and wires personas into the existing enforcement, rather than building enforcement from scratch.
- **Reference personas (from guide):** Engineering → all Claude models, ~5M tokens/day; Sales → Haiku only (explicit Deny Sonnet/Opus + permission boundary), ~500K tokens/day. Pricing/limits are customer examples; keep them as editable defaults.
- **Cutover** (guide §4 Step 6) is a customer runbook (canary → engineering → sales → verify → decommission). Relevant to docs/runbook deliverables, not core product code.
- **Key invariant cross-refs:** `config-sync.md`, `credential-helper-parity.md`, `iam-actions.md`, `quota-requires-oidc.md`, `auth-type-compat.md`, `otel-attribution-chain.md`, `cfn-naming.md`, `region-availability.md`, `stack-ordering.md`, `windows-platform-guards.md`, `issuer-url-format.md`, `azure-tenant-extraction.md`, `keyring-chunking.md`, `binary-distribution.md`, `review-tiers.md` (Tier 1), `pr-standards.md`, `branch-strategy.md` (target `beta`).
