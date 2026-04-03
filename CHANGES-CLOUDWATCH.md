# Migration: OTEL → Bedrock Application Inference Profiles + CloudWatch

## Motivation

The current approach relies on OpenTelemetry (OTEL) to collect usage metrics for Claude models on Bedrock. This architecture has a fundamental problem: **metrics are generated client-side**, meaning that if a user does not correctly configure the OTEL collector, their usage is not tracked. From a cost management perspective, this creates real AWS costs that are not attributed to any user or project.

### Specific Problem

```
Client (Claude Code)
    → otel-helper (local PyInstaller binary)
    → ALB → ECS Fargate (ADOT Collector)
    → CloudWatch EMF
```

If the client does not send OTEL data (missing configuration, network error, outdated binary),
tokens consumed on Bedrock remain completely invisible to cost controls.

### Proposed Solution

Use **Bedrock Application Inference Profiles** (one per user per model) as a server-side
tracking mechanism. Metrics are written directly by AWS Bedrock to CloudWatch regardless
of any client-side configuration.

CloudWatch natively exposes 4 metrics in the `Bedrock` namespace for each invocation:

| CloudWatch Metric | Meaning | Cost Relevance |
|---|---|---|
| `InputTokenCount` | Standard input tokens | Full input cost |
| `OutputTokenCount` | Output tokens | Output cost |
| `CacheReadInputTokenCount` | Tokens read from cache | ~10x cheaper than input |
| `CacheWriteInputTokenCount` | Tokens written to cache | ~1.25x input cost |

Metrics are aggregated per minute → hourly cost controls are fully covered with no gaps.

### Verified Constraints

- Application Inference Profiles limit: **2000 per account per region** (soft limit, can be raised via Service Quota request)
- With 3 models × 600 max users = 1800 profiles → within the default limit with margin
- If growth requires it: request an increase to 3000+ via AWS Service Quotas

---

## Change List

### 1. `source/claude_code_with_bedrock/models.py`

**What:** Add a dedicated `INFERENCE_PROFILE_MODELS` configuration block that defines the
source models to copy when creating Application Inference Profiles. This is the single
place an administrator updates when Anthropic releases new models.

Default configuration:

```python
INFERENCE_PROFILE_MODELS = {
    "opus-4-6": {
        "source_model_arn": "arn:aws:bedrock:{region}::foundation-model/anthropic.claude-opus-4-6-v1",
        "description": "Claude Opus 4.6 - Most capable model",
        "enabled": True,
    },
    "sonnet-4-6": {
        "source_model_arn": "arn:aws:bedrock:{region}::foundation-model/anthropic.claude-sonnet-4-6-20251120-v1:0",
        "description": "Claude Sonnet 4.6 - Balanced performance and cost",
        "enabled": True,
    },
    "haiku-4-5": {
        "source_model_arn": "arn:aws:bedrock:{region}::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        "description": "Claude Haiku 4.5 - Fastest and most cost-effective",
        "enabled": True,
    },
}
```

Also add two helper functions:
- `get_application_profile_name(email: str, model_key: str) -> str`
  Sanitizes the email (replaces `@` and `.` with `-`) and builds the profile name
- `get_application_profile_tags(email: str, claims: dict) -> dict`
  Builds the tag dictionary to apply to the profile from JWT claims

**Why:** Centralizing the model definitions in one place means that when Anthropic releases
a new model version, the administrator only needs to update `INFERENCE_PROFILE_MODELS` —
no changes required in the credential_provider or any other component. The `enabled` flag
allows disabling a model without removing its entry, preserving history.

---

### 2. `source/claude_code_with_bedrock/config.py`

**What:** Add the following fields to the `Profile` dataclass:
- `inference_profiles_enabled: bool = False` — enables/disables the feature
- `inference_profiles_models: list[str]` — list of model keys from `INFERENCE_PROFILE_MODELS`
  for which to create profiles (default: all entries with `enabled: True`)
- `inference_profiles_default_model: str = "sonnet-4-6"` — the model whose ARN is written
  to `~/.claude.json` as the default Claude Code model after first login

**Why:** Making the feature opt-in ensures backward compatibility with existing deployments.
An existing deployment sees no behavioral change until the administrator explicitly sets
`inference_profiles_enabled = true`.

---

### 3. `source/credential_provider/__main__.py`

**What:** Add a `_ensure_user_inference_profiles()` method invoked after `_check_quota()`
and before returning AWS credentials.

**Behavior:**
- For each model in `INFERENCE_PROFILE_MODELS` where `enabled: True`, check whether an
  Application Inference Profile already exists with the naming convention
  `claude-code-{sanitized_email}-{model_key}`
- If it does not exist, create it via `bedrock:CreateInferenceProfile` copying from the
  `source_model_arn` defined in `INFERENCE_PROFILE_MODELS`, with the following tags:
  - `user.email` = user email (from JWT)
  - `model` = model key
  - `cost_center` = JWT claim `custom:cost_center` (if present)
  - `department` = JWT claim `custom:department` (if present)
  - `organization` = JWT claim `custom:organization` (if present)
- Cache the profile ARNs locally (`~/.claude-code-session/{profile}-inference-profiles.json`)
  to avoid API calls on every login
- Creation is **idempotent**: if the profile already exists, return the existing ARN

**Automatic Claude Code configuration (Option A):**
After creating or loading the profiles from cache, automatically patch `~/.claude.json`
with the ARN of the default model (configured via `inference_profiles_default_model`):
```json
{
  "model": "arn:aws:bedrock:eu-central-1:123456789:application-inference-profile/abc1"
}
```
This requires zero manual steps from the end user — their environment is fully configured
at first login, consistent with how the project already auto-configures `~/.aws/config`.

**Why:** The credential_provider is the guaranteed entry point for every user. It is already
the place where JWT validation and quota checks happen, making it the natural location to
ensure profiles exist before the user starts working.

---

### 4. `source/claude_code_with_bedrock/cli/commands/` — new file `profiles.py`

**What:** Add a new CLI command `ccwb profiles` (Option B) with two subcommands:

- `ccwb profiles list` — prints the user's Application Inference Profile ARNs:
  ```
  Your Bedrock Application Inference Profiles:

    opus-4-6   (Claude Opus 4.6)    arn:aws:bedrock:...:application-inference-profile/abc1
    sonnet-4-6 (Claude Sonnet 4.6)  arn:aws:bedrock:...:application-inference-profile/def2
    haiku-4-5  (Claude Haiku 4.5)   arn:aws:bedrock:...:application-inference-profile/ghi3

  Default model ARN (configured in ~/.claude.json):
    arn:aws:bedrock:...:application-inference-profile/def2
  ```

- `ccwb profiles set-default <model_key>` — updates `~/.claude.json` with the ARN of
  the specified model, allowing the user to switch their default model at any time

**Why:** The ARNs are useful beyond Claude Code — users may want to use their personal
inference profiles in other tools (AWS CLI, boto3 scripts, Bedrock Playground, etc.).
The `set-default` subcommand gives users control over which model Claude Code uses
without requiring them to manually copy ARNs.

---

### 5. `deployment/infrastructure/cognito-identity-pool.yaml`

**What:** Update the Cognito authenticated role IAM policy to:

1. Add the permissions required to create and read profiles:
   ```
   bedrock:CreateInferenceProfile
   bedrock:GetInferenceProfile
   bedrock:ListInferenceProfiles
   bedrock:TagResource
   ```

2. Add an ABAC condition on `bedrock:InvokeModel` that restricts access to only the
   profiles whose `user.email` tag matches the authenticated user's identity:
   ```json
   "Condition": {
     "StringEquals": {
       "aws:ResourceTag/user.email": "${cognito-identity.amazonaws.com:sub}"
     }
   }
   ```
   This ensures each user can invoke **exclusively their own profiles**.

**Why:** Explicit isolation requirement — a user must not be able to use another user's
profiles, either accidentally or intentionally.

---

### 6. `deployment/infrastructure/otel-collector.yaml`

**What:** Deprecate the OTEL collector stack. The template is kept in the repository for
compatibility with existing deployments but:
- Add a `Deprecated: true` parameter with an explanatory note
- Update the template README with migration instructions

**Why:** With Bedrock profiles, the OTEL collector on ECS Fargate is no longer needed for
metrics tracking. Removing it reduces operational costs (always-on Fargate task) and
maintenance surface area.

---

### 7. `deployment/infrastructure/metrics-aggregation.yaml`

**What:** Simplify the `metrics_aggregator` Lambda:
- Remove CloudWatch Logs Insights queries on OTEL logs
- Keep only the DynamoDB writes for quota data (still required for real-time quota checks
  in the credential_provider)
- Aggregated usage metrics for dashboards are now read directly from the `Bedrock`
  CloudWatch namespace filtered by user tag

**Why:** The Lambda running every 5 minutes primarily served to aggregate OTEL data into
CloudWatch metrics. With Bedrock profiles this intermediate step is no longer needed.

---

### 8. `deployment/infrastructure/claude-code-dashboard.yaml`

**What:** Update the CloudWatch Dashboard to read metrics from the `Bedrock` namespace
instead of the `ClaudeCode` OTEL namespace. Widgets to update:
- Total tokens per user (dimension: `user.email` tag)
- Token type breakdown (Input / Output / CacheRead / CacheWrite)
- Estimated cost per user and per `cost_center`
- Top N users by consumption

**Why:** The metric source changes namespace and dimensions; the dashboard must reflect
the new structure.

---

## Recommended Implementation Sequence

```
1. models.py           → INFERENCE_PROFILE_MODELS block + helper functions (no external dependencies)
2. config.py           → new fields, fully backward-compatible
3. credential_provider → core profile creation logic + automatic ~/.claude.json patching (Option A)
4. cli/profiles.py     → ccwb profiles list / set-default commands (Option B)
5. cognito IAM policy  → user isolation enforcement (ABAC)
6. dashboard           → updated visualization
7. metrics-aggregation → Lambda simplification
8. otel-collector      → deprecation
```

## Impact on Existing Deployments

| Component | Impact |
|---|---|
| End users | None — profile is created silently on first login |
| Administrators | Must set `inference_profiles_enabled = true` in the config profile |
| AWS costs | Reduction (removal of always-on ECS Fargate OTEL collector) |
| Historical metrics | Existing OTEL data remains in CloudWatch until TTL expiry |
| IAM | Cognito role policy update requires a stack re-deploy |

---

## Security Enhancement: Lambda-based Inference Profile Provisioning

### Motivation

`bedrock:CreateInferenceProfile` and `bedrock:TagResource` were granted directly to the
Cognito federated role. Every authenticated user could call the Bedrock management plane
with their own credentials, which creates unnecessary attack surface:

- A compromised token could create profiles with arbitrary names or tags, confusing
  cost attribution or quota tracking.
- `bedrock:TagResource` is broad — a misconfigured ABAC condition could allow re-tagging
  profiles owned by other users.
- Users calling `CreateInferenceProfile` directly bypass any server-side enforcement of
  naming conventions or tag schema.

### Implemented Architecture

A dedicated Lambda function (`InferenceProfileProvisionerFunction`) is the **sole
principal** with `bedrock:CreateInferenceProfile` and `bedrock:TagResource`. The Cognito
role loses those permissions entirely and gains only `lambda:InvokeFunction` on that
specific function ARN.

```
Before:
  User credentials → bedrock:CreateInferenceProfile (direct)

After:
  User credentials → lambda:InvokeFunction → Lambda (elevated role) → bedrock:CreateInferenceProfile
```

The trust boundary is IAM: the Lambda is only reachable by callers whose SigV4-signed
credentials include `lambda:InvokeFunction` on its ARN. Those credentials are issued only
after the caller's OIDC token has been validated by the credential_provider. No API
Gateway is involved — the Lambda is invoked directly via the AWS SDK.

### Files Changed

#### `deployment/infrastructure/lambda-functions/inference_profile_provisioner/index.py` (new)

Synchronous Lambda handler invoked by the credential_provider at login time.

**Input event**: `{ "email": "user@example.com", "claims": { ...jwt_claims... } }`

The email is passed from the credential_provider (which already validated the JWT) and
is basic-format validated by the Lambda. Claims are used only to build the profile tags.

**Logic**:
- For each enabled model in `INFERENCE_PROFILE_MODELS`:
  - Derive profile name via `_get_profile_name(email, model_key)` (same algorithm as `models.py`)
  - Build tags from email + JWT claims
  - Call `bedrock:CreateInferenceProfile` (idempotent — catches `ConflictException`)
  - On conflict, resolves existing ARN via paginated `bedrock:ListInferenceProfiles`
- Returns `{ "profile_arns": { "opus-4-6": "arn:...", "sonnet-4-6": "arn:...", "haiku-4-5": "arn:..." } }`
- Per-model failures are non-fatal; function returns whatever ARNs it created

The handler code is also inlined in the CloudFormation `ZipFile` block so no separate
deployment step is needed.

#### `deployment/infrastructure/bedrock-auth-cognito-pool.yaml`

Three changes:

1. **Replaced** `AllowBedrockManageInferenceProfiles` IAM statement with
   `AllowInvokeInferenceProfileProvisioner` (`lambda:InvokeFunction` on the provisioner
   ARN, region-scoped). `bedrock:CreateInferenceProfile` and `bedrock:TagResource` are
   gone from the user role.

2. **Added** three new resources (all conditional on `UseInferenceProfiles`):
   - `InferenceProfileProvisionerRole` — Lambda execution role with
     `bedrock:CreateInferenceProfile`, `bedrock:TagResource` (scoped to
     `application-inference-profile/*` in this account), `bedrock:ListInferenceProfiles`,
     `bedrock:GetInferenceProfile`. No invoke permissions.
   - `InferenceProfileProvisionerLogGroup` — CloudWatch log group, 30-day retention.
   - `InferenceProfileProvisionerFunction` — Python 3.12 Lambda, 60s timeout, handler
     code inlined via `ZipFile`.

3. **Updated `ConfigurationJson` output** — expanded from 2 variants to 4
   `(direct | cognito) × (inference profiles enabled | disabled)`. When
   `InferenceProfilesEnabled=true`, CloudFormation automatically injects:
   ```json
   "inference_profiles_enabled": true,
   "inference_profiles_provisioner_arn": "<resolved-lambda-arn>"
   ```
   Users copy this output into `config.json` as before — no manual ARN lookup needed.

#### `source/credential_provider/__main__.py`

`_ensure_user_inference_profiles()` now invokes the Lambda instead of calling Bedrock
directly:

```python
lambda_client = boto3.client("lambda", region_name=region, **user_credentials)
response = lambda_client.invoke(
    FunctionName=provisioner_arn,       # from config: inference_profiles_provisioner_arn
    InvocationType="RequestResponse",
    Payload=json.dumps({"email": email, "claims": token_claims}),
)
```

If `inference_profiles_provisioner_arn` is not set in the config, profile creation is
skipped (the user role has no Bedrock management-plane permissions anyway).

#### `source/claude_code_with_bedrock/config.py`

Added `inference_profiles_provisioner_arn: str = ""` to the `Profile` dataclass.
Populated automatically from the `ConfigurationJson` CloudFormation output.

### Security Improvement Summary

| Threat | Before | After |
|---|---|---|
| Arbitrary profile creation | User calls `CreateInferenceProfile` directly | Only Lambda can; user can only trigger it via IAM-authenticated invoke |
| Tag manipulation | User has `TagResource` on profile ARNs | `TagResource` removed from user role entirely |
| Naming convention bypass | Profile name built client-side | Lambda enforces canonical naming server-side |
| Tag schema enforcement | Tags built client-side | Lambda builds tags from JWT claims centrally |
| Blast radius of stolen token | Can create/tag profiles | Can only invoke provisioner (which enforces its own naming) |

### Impact on Existing Deployments

| Component | Impact |
|---|---|
| End users | None — flow is identical from the user's perspective |
| Administrators | Redeploy `bedrock-auth-cognito-pool` with `InferenceProfilesEnabled=true`; copy the new `ConfigurationJson` output — provisioner ARN is included automatically |
| AWS costs | Marginal Lambda invocation cost per first login per user (negligible at scale) |
| IAM | Cognito role loses `bedrock:CreateInferenceProfile` and `bedrock:TagResource` |
