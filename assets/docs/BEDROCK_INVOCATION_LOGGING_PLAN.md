# Bedrock Invocation Logging — Implementation Plan

**Ticket:** IPES-174 — _Enable Bedrock Invocation Logging for Claude Code and export to CloudWatch/S3_
**Owner:** Anand Joshi (ramp-up task; ownership moving to AI Infrastructure team)
**Stakeholders:** Isaac Wong (requester — audit + sampling analysis), Raouf Aghrout (prior owner), Stefan Mihaylov (secondary consumer — plugin/skill counting), Dennis Zhao (AI Infra team)
**Target AWS account:** `genai-studio-dev` (136113531821)
**Target Bedrock region:** `us-west-2` (where Claude Code actually invokes models)

---

## 1. Goal

Enable **Bedrock Model Invocation Logging** in our Bedrock region so that every Claude Code call captures the full request/response payload (including `identity.arn` → user email, tool-use blocks, MCP tool names, skills, plugins) and lands in both:

1. **CloudWatch Logs** — for real-time querying (Logs Insights) during incident/triage.
2. **S3** — for long-term audit retention and daily usage-sampling pipelines.

Stefan & Isaac confirmed (Apr 13 Slack) that the data they need lives inside the invocation payload:

- `identity.arn` tail → user email (role session name — federated Okta login)
- `input.inputBodyJson.messages[0].content` → available MCP tools (declared at session start)
- `output.outputBodyJson.content[]` with `type: tool_use` → actually-executed MCP tool / Skill

This data is **not** in Honeycomb (Honeycomb has no payload, just OTEL spans), so this is the only audit-grade source.

**Confirmed field paths (Isaac, Apr 13 — from AWS support):**

| What | Path in Bedrock log | Example |
|---|---|---|
| User identity | `identity.arn` tail | `arn:aws:sts::<acct>:assumed-role/BedrockOktaFederatedRole/user@smartnews.com` |
| Declared MCP tools | `input.inputBodyJson.messages[0].content` — inside `<available-deferred-tools>` tag | `AskUserQuestion`, `WebFetch`, … |
| Executed MCP tool | `output.outputBodyJson.content[]` where `type == "tool_use"` and `name` starts with `mcp__<server>__<tool>` | `mcp__ide__executeCode` |
| Executed Skill | `output.outputBodyJson.content[]` where `type == "tool_use"` and `name == "Skill"` | skill name is in the block's `input.skill` field |

---

## 2. Decisions & open questions

### 2.1 Agreed from Slack (Raouf's Apr 15 message)

| Item | Value |
|---|---|
| Enable logging | yes |
| CloudWatch Logs retention | **7 days** |
| S3 Standard retention | **30 days** |
| S3 Glacier retention | **60 days** (after transition from Standard at day 30) |
| Total S3 lifespan | **90 days** (then expire) |
| Log scope | Text **and** image data (Claude Code sends screenshots; full-fidelity audit requires both) |
| Deployment region | `us-west-2` (where Bedrock runs) |

### 2.2 Defaults I'm taking unless you say otherwise

| Decision | Default | Reason to revisit |
|---|---|---|
| **Encryption** | AWS-managed keys (SSE-S3 for bucket, AWS-managed key for CW log group) | If SmartNews security requires a customer-managed KMS key, we add a CMK stack + update the logging IAM role trust. |
| **Access model** | Same-account. Read for Isaac's sampling pipeline happens inside `genai-studio-dev`. | Cross-account read (from SN `dev`/`prd`) would need a bucket policy + KMS grant. |
| **Log format** | Bedrock's native JSON (one event per invocation); no transformation | Stefan/Isaac said Logs Insights + ad-hoc S3 SELECT/Athena is sufficient. |
| **Ownership of enablement** | `ccwb` CLI + CloudFormation (not click-ops) so it's reproducible and rebaseable from upstream | Same pattern as every other stack. |

### 2.3 Resolved from Apr 6–13 Slack thread (Isaac ↔ Raouf)

- Isaac's use case is **anonymized sampling** aggregated to div/team level — no per-user identification. Daily sampling pipeline will run separately.
- Retention numbers (7d CW / 30d S3 / 60d Glacier) were Raouf's cost-conscious counter-proposal to Isaac's original 7–30d CW + 90d+ S3. Isaac accepted.
- Stefan confirmed invocation logs will satisfy his plugin/skill counting ticket too — we don't need a second logging sink.

### 2.4 Worth clarifying with stakeholders (non-blocking)

1. **PII in payloads** — Raw Claude Code prompts can include source code, file paths, and secrets pasted by users. 90-day retention of full payloads is a meaningful privacy surface. Is legal/security aware this data is stored? (Not blocking v1; worth an FYI email.)
2. **Isaac's sampling pipeline location** — Where does his "daily sampling pipeline" run? If it's outside `genai-studio-dev`, we need a bucket policy + he needs a role there. I'll hand him read-only access to the bucket in the same account and leave cross-account as a fast follow.
3. **Image-data toggle** — Bedrock exposes separate `textDataDeliveryEnabled` / `imageDataDeliveryEnabled` toggles. Logging images 90 days is the biggest cost driver. Confirm audit needs images; if not, flipping image off cuts S3 size significantly.
4. **Who owns this long-term?** — Per Dai Zhao (Apr 18), ownership of CCE is transferring to AI Infra. I'll build it as if I'll maintain it, and document handover in §9.

---

## 3. Architecture

```
┌────────────────────────────────┐      ┌─────────────────────────────┐
│ Claude Code user laptop        │      │ genai-studio-dev (us-west-2) │
│                                │      │                              │
│ credential-process ──Okta OIDC─┼──────► STS AssumeRoleWithWebIdentity│
│                                │      │        │                     │
│ Bedrock SDK call ──────────────┼──────► Bedrock Runtime              │
│   (global.anthropic.claude-*)  │      │        │ (logging hook)       │
└────────────────────────────────┘      │        ├──► CloudWatch Logs  │
                                        │        │     /aws/bedrock/   │
                                        │        │     claude-code-    │
                                        │        │     invocations     │
                                        │        │     (7d retention)   │
                                        │        │                     │
                                        │        └──► S3 bucket         │
                                        │              sn-cce-bedrock-  │
                                        │              invocation-logs- │
                                        │              <acct>-usw2      │
                                        │              ├ 0-30d  Standard│
                                        │              ├ 30-90d Glacier │
                                        │              └ >90d   expire  │
                                        └─────────────────────────────┘
```

**Key constraint:** Bedrock Model Invocation Logging is **account- and region-scoped**, with a single configuration per region (`PutModelInvocationLoggingConfiguration` is a singleton call — not per-model, not per-role). That means:

- Configuration must live in `us-west-2` (where our invocations go).
- The CW log group and S3 bucket must also be in `us-west-2` — same-region only.
- **Our CloudFormation infra region is `ap-northeast-1`**, so this stack must be deployed to `us-west-2` specifically. The `ccwb` CLI currently deploys everything to `profile.aws_region` (Tokyo). We need a second region target for this stack only.

---

## 4. Resources to create

All in `us-west-2`, new CloudFormation template `deployment/infrastructure/bedrock-invocation-logging.yaml`:

| Resource | Purpose |
|---|---|
| `AWS::S3::Bucket` (`sn-cce-bedrock-invocation-logs-<acctid>-usw2`) | Stores raw JSON invocation logs. Versioning off (cost), public access fully blocked, SSE-S3, object ownership = BucketOwnerEnforced (disables ACLs). |
| Bucket lifecycle rule | Days 0–30: `STANDARD`. Day 30: transition to `GLACIER` (= Flexible Retrieval; not Deep Archive). Day 90: expire. Abort incomplete multipart uploads at day 7. |
| `AWS::Logs::LogGroup` (`/aws/bedrock/claude-code-invocations`) | 7-day retention. |
| `AWS::IAM::Role` (`BedrockInvocationLoggingRole`) | Bedrock service role. Trust: `bedrock.amazonaws.com`. Permissions: `logs:CreateLogStream`/`PutLogEvents` on the log group + `s3:PutObject` on the bucket. Conditions: `aws:SourceAccount` = account ID and `aws:SourceArn` = wildcard against Bedrock logging ARN (confused-deputy protection). |
| Lambda-backed custom resource (`AWS::CloudFormation::CustomResource`) | Enables logging via `bedrock:PutModelInvocationLoggingConfiguration`. **There is no native CFN resource** for this API — confirmed by checking the CloudFormation schema registry and the `AWS_Bedrock.html` resource list (as of 2026-04). The custom resource is inline Python (~60 LOC) embedded in the template via `Code.ZipFile`; it calls Put on Create/Update and Delete on Delete. |
| Bucket policy | Allow only `bedrock.amazonaws.com` to `PutObject` (scoped by `aws:SourceAccount`). Deny all non-TLS requests (`aws:SecureTransport=false`). |

**Not created:** KMS CMK (using AWS-managed), VPC endpoints (Bedrock traffic already goes over the AWS backbone from Bedrock → CW/S3).

---

## 5. Implementation steps

### Step 1 — New CloudFormation template

**File:** `deployment/infrastructure/bedrock-invocation-logging.yaml`

Parameters:
- `LogGroupName` (default `/aws/bedrock/claude-code-invocations`)
- `BucketNamePrefix` (default `sn-cce-bedrock-invocation-logs`)
- `CloudWatchRetentionDays` (default `7`)
- `S3StandardDays` (default `30`)
- `S3GlacierDays` (default `60`)
- `LogTextData` (default `true`)
- `LogImageData` (default `true`)
- `LogEmbeddingData` (default `true`) — Claude Code doesn't use embeddings but the API requires a value

Outputs: log group ARN, bucket name, bucket ARN, Bedrock logging role ARN.

### Step 2 — Wire into CLI

Edit `source/claude_code_with_bedrock/config.py` — add to `Profile`:

```python
invocation_logging_enabled: bool = False
invocation_logging_region: str = "us-west-2"  # must match Bedrock region
invocation_logging_cw_retention_days: int = 7
invocation_logging_s3_standard_days: int = 30
invocation_logging_s3_glacier_days: int = 60
```

Edit `source/claude_code_with_bedrock/cli/commands/deploy.py`:
- Add `"logging"` stack type (desc: "Bedrock Invocation Logging (CW + S3)").
- When deploying this stack, instantiate a **second** `CloudFormationManager(region=profile.invocation_logging_region)` — do **not** use `profile.aws_region` (Tokyo).
- Include it in "deploy all" when `profile.invocation_logging_enabled` is true.

Edit `source/.ccwb-config/config.json` — flip `invocation_logging_enabled: true` (config is committed per CLAUDE.md).

Edit `destroy.py` and `status.py` similarly (small additions — teardown must also hit us-west-2).

### Step 3 — IAM: grant the federated role read access to logs (optional, for operators)

We do **not** add read access to all CCE users. The federated role `BedrockOktaFederatedRole` stays minimal (invoke-only). Admins read logs through their admin Okta role or the Console.

### Step 4 — Validation / pre-commit

The existing `scripts/validate-cloudformation.sh` + `cfn-lint` will pick up the new template automatically. Nothing to wire in.

### Step 5 — Docs

Add a short section to `assets/docs/MONITORING.md` (or new `INVOCATION_LOGGING.md`) covering:
- What's logged, where, retention
- Sample Logs Insights queries (per-user activity, top MCP tools, top skills)
- How to restore from Glacier (Flexible Retrieval = 1–5 min for expedited, 3–5 hrs for standard)
- Privacy note — payloads may contain source code / secrets

### Step 6 — Test plan

**In `genai-studio-dev`:**

1. `poetry run ccwb deploy logging --dry-run` — sanity-check template.
2. `poetry run ccwb deploy logging` — actually create the stack in us-west-2.
3. From a Mac with Claude Code installed:
   - Run a trivial Claude Code prompt that uses at least one MCP tool and one Skill (so we can verify both show up in `output.outputBodyJson.content[]`).
4. Verify in AWS Console (us-west-2):
   - CloudWatch log group has a log stream with an event within ~1 minute.
   - Confirm `identity.arn` tail = my email.
   - Confirm `input.inputBodyJson.messages[0].content` contains the `<available-deferred-tools>` list.
   - Confirm `output.outputBodyJson.content[]` has a `tool_use` block.
5. S3: confirm an object lands under `AWSLogs/<acct>/BedrockModelInvocationLogs/us-west-2/YYYY/MM/DD/HH/…`.
6. CLI: `aws logs start-query` with `fields @timestamp, identity.arn | filter identity.arn like "anand"` and confirm the event is queryable.
7. Confirm lifecycle rule is applied (`aws s3api get-bucket-lifecycle-configuration`).
8. `poetry run ccwb destroy` — confirm clean teardown (we disable logging first via the custom resource, then delete the bucket — need `DeletionPolicy: Retain` or an emptying Lambda on the bucket since CFN won't delete non-empty buckets).

### Step 7 — Rollout

Low-risk: this only adds sinks. It does **not** change the user-facing auth flow, the federated role's permissions, or the `credential-process` binary. No new MDM push needed.

Steps:
1. Merge → deploy to `genai-studio-dev` via `ccwb deploy logging`.
2. Let it run 24 h, confirm events accumulate.
3. Tell Isaac the bucket/log group names so he can build his sampling pipeline.
4. Tell Stefan the Logs Insights query for plugin/skill counts.

### Step 8 — Hand over to AI Infrastructure team

Bundle: this plan doc + the template + the `ccwb` CLI changes + a 10-line runbook for destroy/re-enable. Meeting with Dennis + team after rollout.

---

## 6. Cost estimate

Rough order of magnitude (Tokyo-based users ≈ 100 active devs, ~50 Claude Code sessions/day/user, avg 20 invocations/session, avg payload ~8 KB text + occasional screenshot):

- **Invocations/day:** 100 × 50 × 20 = **100k/day** = ~3M/month
- **CloudWatch Logs ingestion:** 100k × ~8 KB × 30 = ~24 GB/month ingest, 7-day storage. At Tokyo rates (~$0.76/GB ingest, $0.033/GB-month storage): **~$18 + $1 = ~$20/mo**. (us-west-2 is slightly cheaper.)
- **S3 Standard (first 30 days):** ~24 GB × 30 days of accumulation ≈ 720 GB-months average. **~$17/mo.**
- **S3 Glacier Flexible (days 30–90):** ~48 GB × 60 days at $0.0036/GB-mo: **~$0.17/mo.**
- **Requests:** negligible (<$1/mo).
- **Image payloads:** if screenshots averaging ~200 KB are logged for 10 % of calls, roughly **10×** the base S3 cost → revisit if logged volume is unexpectedly high.

**All-in expected:** under **~$40/month** with text-only; under **~$200/mo** worst-case with heavy screenshot usage. Easily offset by the audit value.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Custom resource for `PutModelInvocationLoggingConfiguration` fails to clean up on stack deletion, leaving logging enabled pointing to a deleted bucket | Use `AWS::Bedrock::LoggingConfiguration` (native CFN) if available. If falling back to custom resource, implement `Delete` handler that explicitly calls `bedrock:DeleteModelInvocationLoggingConfiguration` and make the bucket `DeletionPolicy: Retain` for first rollout to avoid orphaned log destinations. |
| Only one Bedrock invocation-logging config exists per region — if someone in the same account already enabled logging manually, our CFN will overwrite it | Run `aws bedrock get-model-invocation-logging-configuration --region us-west-2` before first deploy. The account is dedicated to CCE; very low risk. |
| Global inference profile (`global.*`) logs land in the source region, not us-west-2 | Per AWS docs, cross-region inference logs land in the region where the *request* was made. Claude Code's config sets `AWS_REGION=us-west-2`, so we're good. Verify during Step 6. |
| Logs contain secrets (API keys pasted into prompts) | Documented in the privacy note. Bucket is locked down (account-only, TLS-only, no public). 90-day lifecycle limits blast radius. |
| Stack deletion fails because S3 bucket is non-empty | Either keep `DeletionPolicy: Retain` on the bucket (safer) or add a small Lambda custom-resource that empties it on delete. Default to Retain for v1. |

---

## 8. Files that changed (as built)

New:
- `deployment/infrastructure/bedrock-invocation-logging.yaml` — stack with S3 bucket, CW log group, Bedrock service role, and a Lambda-backed custom resource that calls `PutModelInvocationLoggingConfiguration`. Lambda code is inline (`Code.ZipFile`), no separate file needed.
- `assets/docs/BEDROCK_INVOCATION_LOGGING_PLAN.md` (this file)

Modified:
- `source/claude_code_with_bedrock/config.py` — added `invocation_logging_*` fields to `Profile`
- `source/claude_code_with_bedrock/cli/commands/deploy.py` — new `logging` stack; uses a second `CloudFormationManager` pinned to `profile.invocation_logging_region` (us-west-2)
- `source/claude_code_with_bedrock/cli/commands/destroy.py` — teardown (respects region override; adds manual-cleanup hint for the retained S3 bucket)
- `source/claude_code_with_bedrock/cli/commands/status.py` — shows logging stack status
- `source/.ccwb-config/config.json` — enabled the feature with SmartNews defaults
- `CLAUDE.md` — added a line under "SmartNews-specific customizations"

No changes to:
- `credential_provider/__main__.py`
- `package.py` / installer scripts
- `bedrock-auth-okta.yaml` (user-facing federated role unchanged)
- End-user binary or MDM-distributed zip (this is pure AWS-side config)

---

## 9. Handover notes (AI Infra team)

- Enable/disable toggle: `invocation_logging_enabled` in `source/.ccwb-config/config.json`.
- Stack lives in **us-west-2**, not Tokyo — don't assume `profile.aws_region`.
- `bedrock:PutModelInvocationLoggingConfiguration` is singleton per region per account — do not enable it from two places.
- If retention needs to change, edit the Profile defaults + redeploy; lifecycle rule changes apply to existing objects on their next transition check (within 24h).
- To add cross-account read access for a new analysis pipeline: add a `Statement` to the bucket policy with `Principal: arn:aws:iam::<acct>:root` + `Condition: aws:PrincipalArn` scoped to the reader role. No KMS grants needed (SSE-S3).

---

## 10. Proposed order of execution

1. Ship this plan, get a thumbs-up from Raouf (blesses retention) + Dennis (blesses AI-Infra ownership path).
2. Decide on the 4 open questions in §2.3 (PII FYI, Isaac's pipeline location, image-data toggle, KMS). None are blocking; defaults are safe.
3. Build + test in `genai-studio-dev` per §5.
4. Monitor cost + volume for a week, tighten lifecycle if needed.
5. Hand over doc + runbook to AI Infra.
