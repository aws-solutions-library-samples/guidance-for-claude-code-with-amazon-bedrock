# Bedrock Access Enforcer

Server-side enforcement of per-user monthly USD spend quotas for Claude Code on Bedrock.

A scheduled Lambda (`bedrock-access-enforcer`, every 30 min) pulls the list of users
who are **at/over their monthly limit** from the SmartNews quota API and rewrites the
**`DenyBedrock-users`** inline policy on the `BedrockOktaFederatedRole` IAM role. Any
user in that list is denied `bedrock:*` at the IAM layer — a hard block that the
client-side quota check in `credential_provider` (advisory, fail-open) cannot enforce.

- **Stack template:** `deployment/infrastructure/bedrock-access-enforcement.yaml`
- **Stack type / name:** `bedrock-access` → `claude-code-auth-bedrock-access` (Tokyo, `ap-northeast-1`)
- **Handler source of truth:** `index.py` in this directory (unit-tested)
- **Deployed code:** an **inline copy** of `index.py` inside the template's
  `Lambda::Function.Code.ZipFile` (no S3 artifacts bucket is required — see below)

## What it does, precisely

1. Reads the quota API bearer token from Secrets Manager
   (`shared/claude-code-quota-api-token`, JSON key `quota_api_token`).
2. `GET {QUOTA_API_URL}?min_percent={BLOCK_THRESHOLD_PERCENT}` (default 100).
3. Converts each over-quota `email` into the exact `aws:userid` its STS session uses:
   `*:claude-code-<localpart>` where `<localpart>` = `email.split("@")[0]`, truncated
   to 32 chars, with any char outside `[\w+=,.@-]` replaced by `-`.
   **This mirrors `credential_provider/__main__.py`'s `RoleSessionName` logic exactly.**
   It is always the local part — never the full email — regardless of domain.
4. Overwrites **only** the `DenyBedrock-users` inline policy (one `Deny` statement,
   `bedrock:*`, `Resource: *`, `StringLike aws:userid` = the block list). It never
   touches the attached `BedrockAccessPolicy`, the trust policy, or anything else.
5. **Idempotent:** if the desired list already matches the current policy, it does
   nothing (no `PutRolePolicy`, no CloudTrail noise).

### Fail-safe behavior (important)

If the quota API call fails (network / non-200 / parse error), the handler **re-raises
and does NOT modify the policy**. A transient API outage can therefore never silently
unblock everyone — the last-known block list stays in force. When the API succeeds but
returns *zero* over-quota users, the deny list is set to a single never-match sentinel
(`*:claude-code-__none__`) because IAM rejects an empty `StringLike` list.

### Slack notifications

If `SLACK_CHANNEL` is set (SmartNews: `#claude-code-alerts`), the Lambda posts to Slack
via `chat.postMessage` using a bot token from Secrets Manager
(`shared/claude-code-alerts-slack-bot-token`, JSON key `slack_bot_token`):

- **On a block-list change:** one message with the current total (`now blocking N
  users`) plus `Newly blocked` / `Newly unblocked` deltas. Idempotent no-op runs post
  nothing. Pure reformat churn (a userid in both added and removed) is suppressed so it
  doesn't read as a spurious unblock.
- **On error:** alerts are **suppressed until `SLACK_FAILURE_THRESHOLD` (default 3)
  runs fail in a row.** A single transient quota-API blip (see below) is therefore
  silent; only a sustained problem pages the channel — and it pages **once** (on the run
  that crosses the threshold), not on every subsequent failed run. The message is
  sanitized (exception type + first 200 chars, no secrets, no traceback), notes the
  block list was left unchanged, and the error re-raises so the invocation is marked
  failed. When the next run succeeds after an alerting streak, a
  `:white_check_mark: … recovered` message is posted.

Slack posting is best-effort: a Slack failure logs but never breaks enforcement or
un-does the policy update. The bot must be a member of the channel
(`/invite @Bedrock-Bouncer`); only the `chat:write` scope is required to post.

### Consecutive-failure suppression & HTTP timeout

The quota API's time-to-first-byte is slow and variable (observed ~2.6s steady,
~7.4s cold) and **intermittently exceeded the old 10s HTTP read timeout**, producing
bursts of `TimeoutError: The read operation timed out` in Slack (each EventBridge async
retry posted its own alert). Two changes address this:

- **`HTTP_TIMEOUT_SECONDS` raised 10 → 25** (kept well under the 60s Lambda timeout).
- **Failure alerts gated behind a consecutive-failure counter** (`SLACK_FAILURE_THRESHOLD`,
  default 3). The streak is persisted in the function's **own `CONSECUTIVE_FAILURES`
  env var** via `lambda:UpdateFunctionConfiguration` (scoped to this one function) — no
  DynamoDB/S3/table needed. On success the counter resets to 0 (writing config only if
  it was non-zero, to avoid churn).

> ⚠️ **The env-var counter is serial-safe only, NOT concurrency-safe.** It relies on
> runs never overlapping — safe at `rate(30 minutes)` where a run finishes in seconds.
> If you ever shorten the schedule below a single run's worst-case duration (or add a
> manual invoke while a scheduled run is in flight), two invocations could read the same
> `CONSECUTIVE_FAILURES` and last-writer-wins, miscounting the streak. It self-heals on
> the next clean serial run. If you need sub-minute cadence, move the counter to
> DynamoDB (atomic `ADD`) or a CloudWatch metric + alarm instead.

Note: a stack `deploy` reseeds `CONSECUTIVE_FAILURES` to `0` (the template sets it),
so deploying resets any in-flight failure streak — harmless.

### AFT permissions boundary (this account)

`genai-studio-dev` enforces an AWS Control Tower / AFT permissions boundary
(`arn:aws:iam::136113531821:policy/aft/aft-boundary`) that **denies `iam:CreateRole`
for roles created without that boundary**. The template's `PermissionsBoundaryArn`
parameter (config `bedrock_access_permissions_boundary_arn`) attaches it to the Lambda
execution role. Leave the parameter empty in accounts without such a guardrail.

## One-time setup (AWS CLI, already done)

The quota API token lives in Secrets Manager (tagged `Shared=true`, which the
`BedrockAccessPolicy` already permits reading — but this Lambda uses its own scoped
`secretsmanager:GetSecretValue` on this secret ARN):

```bash
source env.sh   # aft-power-user creds
aws secretsmanager create-secret \
  --name shared/claude-code-quota-api-token \
  --description "Bearer token for the SmartNews quota-usage-export API (Bedrock access enforcement Lambda)" \
  --secret-string '{"quota_api_token":"<TOKEN>"}' \
  --region ap-northeast-1 \
  --tags Key=Shared,Value=true Key=Purpose,Value=bedrock-access-enforcement
```

Rotate the token later with:
```bash
aws secretsmanager put-secret-value --secret-id shared/claude-code-quota-api-token \
  --secret-string '{"quota_api_token":"<NEW_TOKEN>"}' --region ap-northeast-1
```
No redeploy needed — the Lambda reads the secret on every run.

## Deploy — Poetry only, this module only

From `source/` (uses the project's normal deploy pipeline; deploys **only** this stack,
nothing else):

```bash
cd source
poetry run ccwb deploy bedrock-access              # create/update just this stack
poetry run ccwb deploy bedrock-access --dry-run    # preview
poetry run ccwb deploy bedrock-access --show-commands
```

Deploy needs admin creds in the shell (`source ../env.sh`). Because the Lambda code is
inlined in the template (stdlib + boto3 only), there is **no packaging step and no S3
bucket dependency** — unlike the `dashboard`/`quota` stacks, which require the
monitoring `networking` stack's artifacts bucket (not deployed here).

> `poetry run ccwb deploy` (no args) also deploys this stack when
> `bedrock_access_enforcement_enabled: true` in `.ccwb-config/config.json` (it is, for
> SmartNews). Set it to `false` to exclude it from deploy-all while still allowing the
> explicit `deploy bedrock-access`.

## Updating the Lambda code

The template holds the **authoritative deployed copy** of the handler; `index.py` here
is the readable, unit-tested source of truth. Keep them in sync:

1. Edit `index.py` (this directory) and update the tests.
2. Copy the changes into the `Code.ZipFile` block of
   `deployment/infrastructure/bedrock-access-enforcement.yaml` (indent to match).
3. Test + validate, then deploy only this stack:
   ```bash
   cd source
   poetry run pytest tests/test_bedrock_access_enforcer.py -q
   poetry run cfn-lint ../deployment/infrastructure/bedrock-access-enforcement.yaml
   poetry run ccwb deploy bedrock-access
   ```

## Verify / operate (AWS CLI, ad-hoc)

```bash
source env.sh

# Invoke once now (don't wait for the schedule)
aws lambda invoke --function-name bedrock-access-enforcer \
  --region ap-northeast-1 /tmp/out.json && cat /tmp/out.json

# Inspect the resulting block list
aws iam get-role-policy --role-name BedrockOktaFederatedRole \
  --policy-name DenyBedrock-users --output json

# Logs
aws logs tail /aws/lambda/bedrock-access-enforcer --region ap-northeast-1 --follow
```

## Config fields (in `source/.ccwb-config/config.json`)

| field                                | default                                   | meaning                                      |
| ------------------------------------ | ----------------------------------------- | -------------------------------------------- |
| `bedrock_access_enforcement_enabled` | `false` (repo default) / `true` (SN)      | include in `deploy` (all)                    |
| `bedrock_access_role_name`           | `BedrockOktaFederatedRole`                | role whose deny policy is managed            |
| `bedrock_access_deny_policy_name`    | `DenyBedrock-users`                       | inline policy overwritten                    |
| `bedrock_access_quota_export_url`    | `.../api/quota-usage-export`              | quota API base URL                           |
| `bedrock_access_block_threshold`     | `100`                                     | block users at/over this monthly percent     |
| `bedrock_access_quota_token_secret`  | `shared/claude-code-quota-api-token`      | Secrets Manager id for the bearer token      |
| `bedrock_access_schedule`            | `rate(30 minutes)`                        | EventBridge schedule                         |
| `bedrock_access_slack_channel`       | `` (empty) / `#claude-code-alerts` (SN)   | Slack channel; empty disables notifications  |
| `bedrock_access_slack_token_secret`  | `shared/claude-code-alerts-slack-bot-token` | Secrets Manager id for the Slack bot token |
| `bedrock_access_http_timeout_seconds`| `25`                                      | HTTP read timeout for quota/Slack calls (< 60s Lambda timeout) |
| `bedrock_access_slack_failure_threshold` | `3`                                   | alert Slack only after N consecutive failed runs |
| `bedrock_access_permissions_boundary_arn` | `` / `…/aft/aft-boundary` (SN)       | IAM boundary for the Lambda role (AFT accts) |

## Tests

`source/tests/test_bedrock_access_enforcer.py` — pure-logic unit tests (userid
derivation incl. truncation/sanitization, list diffing, empty→sentinel, and the
fail-safe "API error ⇒ never call PutRolePolicy" guarantee). boto3 is mocked; no AWS
calls. Run: `cd source && poetry run pytest tests/test_bedrock_access_enforcer.py -q`.
