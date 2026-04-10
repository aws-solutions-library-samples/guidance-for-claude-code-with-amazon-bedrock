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

---

## Direct STS Federation: Session Tags via OIDC JWT Claims

### Problem

When `federation_type = direct` is used (`AssumeRoleWithWebIdentity` without Cognito
Identity Pool), the IAM policy condition:

```yaml
'aws:ResourceTag/user.email': '${aws:PrincipalTag/UserEmail}'
```

requires the session principal tag `UserEmail` to be populated. Unlike Cognito Identity
Pool (which uses `IdentityPoolPrincipalTag` to map OIDC claims to principal tags),
`AssumeRoleWithWebIdentity` does **not** accept a `Tags` parameter in the API call.

Session tags must instead be embedded in the JWT token issued by the Identity Provider
under the reserved claim `https://aws.amazon.com/tags`.

### JWT Claim Format

AWS STS reads session tags from the following JWT claim structure:

```json
{
  "https://aws.amazon.com/tags": {
    "principal_tags": {
      "UserEmail": ["user@example.com"],
      "UserId": ["provider-user-id"],
      "UserName": ["User Name"]
    },
    "transitive_tag_keys": ["UserEmail", "UserId", "UserName"]
  }
}
```

**Rules:**
- Tag values must be **single-element arrays** (not plain strings)
- `transitive_tag_keys` must be a JSON array of strings
- Tag values allow letters, numbers, spaces and `_ . : / = + - @` — the `|` character
  (used in Auth0 `sub` claims like `auth0|69d51f38...`) is **not allowed** and must be sanitized
- The outer key is exactly `https://aws.amazon.com/tags` with no trailing characters

### Code Changes

#### `source/credential_provider/__main__.py`

- Reverted incorrect `Tags` parameter on `assume_role_with_web_identity` call (`AssumeRoleWithWebIdentity` does not support the `Tags` API parameter — session tags must come from JWT claims)
- Updated comment to document the JWT claim mechanism

#### `source/claude_code_with_bedrock/cli/commands/deploy.py`

- Fixed secret name extraction from ARN: removed regex `-[A-Za-z0-9]{6}$` that incorrectly
  stripped meaningful name suffixes like `-secret` (6 alphanumeric chars matches the pattern)
- Added `markup=False` to Rich debug print to prevent `:secret:` in ARNs rendering as `㊙`

#### `source/claude_code_with_bedrock/cli/utils/aws.py`

- `get_stack_outputs()` now silently returns `{}` on `ValidationError` (stack does not exist)
  instead of printing an error — avoids noise when optional stacks (e.g. OTEL monitoring)
  are not deployed

---

## Identity Provider Setup Guides

### Auth0

To enable session tags with direct STS federation, configure an Auth0 **Action** on the
post-login flow that injects the `https://aws.amazon.com/tags` claim into the ID token.

#### Step 1 — Create the Action

1. In the Auth0 Dashboard, go to **Actions** → **Triggers** → **post-login**
2. Click **+** → **Build Custom**
3. Name it (e.g. `AWS Session Tags`) and paste the following code:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  if (event.user.email) {
    // Sanitize UserId: AWS tag values do not allow '|' (used in Auth0 sub claims)
    const sanitizedUserId = event.user.user_id.replace(/[^a-zA-Z0-9 _.:/=+\-@]/g, '-');

    api.idToken.setCustomClaim('https://aws.amazon.com/tags', {
      principal_tags: {
        UserEmail: [event.user.email],
        UserId: [sanitizedUserId],
        UserName: [event.user.name || event.user.email]
      },
      transitive_tag_keys: ['UserEmail', 'UserId', 'UserName']
    });
  }
};
```

4. Click **Deploy**

#### Step 2 — Add the Action to the Flow

1. In **Actions** → **Triggers** → **post-login**, drag your new action between **Start**
   and **Complete**
2. Click **Apply**

#### Step 3 — Verify

Clear the credential cache and re-authenticate:

```bash
COGNITO_AUTH_DEBUG=1 credential-process --profile <your-profile> --clear-cache
COGNITO_AUTH_DEBUG=1 credential-process --profile <your-profile>
```

In the `=== ID Token Claims ===` debug output, confirm `https://aws.amazon.com/tags` is
present with values wrapped in arrays and that `UserId` contains no `|` character.

#### Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `Unable to validate tags` | Tag values are plain strings, not arrays | Wrap each value in `[...]` |
| `principal_tags passed in claim is not in correct format` | Invalid characters in tag value (e.g. `\|`) | Sanitize `UserId` with the regex above |
| `https://aws.amazon.com/tags` missing from token | Action not deployed or not added to flow | Check Action status is **Deployed** and it appears in the post-login flow diagram |

---

### Microsoft Entra (Azure AD)

Entra has a significant limitation for this use case: **JWT ID tokens cannot contain
custom claims with URL-namespaced keys** (`https://aws.amazon.com/tags`). URL-namespaced
claim names are only supported in SAML tokens, not JWTs. Additionally, claim values in
Entra are always strings — nested JSON objects are not natively emitted.

#### Recommended Approach: Cognito Identity Pool Federation

Use Entra as the OIDC provider feeding into a **Cognito Identity Pool**, which natively
maps OIDC claims to session principal tags via `IdentityPoolPrincipalTag`:

```yaml
IdentityPoolPrincipalTag:
  Type: AWS::Cognito::IdentityPoolPrincipalTag
  Properties:
    IdentityPoolId: !Ref CognitoIdentityPool
    IdentityProviderName: !Ref EntraDomain
    UseDefaults: false
    PrincipalTags:
      UserEmail: email
      UserId: sub
      UserName: name
```

Set `federation_type: cognito` in the profile config. The Cognito path handles tag
injection transparently — no changes to the Entra application are required.

#### Entra Application Configuration (for Cognito path)

In the Azure portal:

1. **App registrations** → your app → **Token configuration**
2. Add optional claims for the **ID** token: `email`, `preferred_username`, `given_name`, `family_name`
3. Ensure the app has **User.Read** delegated permission granted

The `email` claim maps to `UserEmail` via the `IdentityPoolPrincipalTag` configuration
above — no additional Entra configuration is needed for the tag injection itself.

---

## Server-Side Quota Enforcement via Inference Profile Tagging

### Problem

The existing quota check is **client-side**: the credential provider calls a quota API before
issuing credentials, but only if `quota_api_endpoint` is present in `config.json`. A user who
removes that field (or installs the credential provider from scratch) bypasses enforcement
entirely. The credential TTL cache also means a blocked user can continue working for up to
30 minutes after exceeding quota.

### Solution: IAM Tag Condition + QuotaEnforcer Lambda

Every inference profile carries a `status` tag (`enabled` or `disabled`). The IAM policy on
the federated role includes a condition that checks this tag on **every Bedrock API call**:

```yaml
Condition:
  StringEquals:
    'aws:ResourceTag/user.email': '${aws:PrincipalTag/UserEmail}'
    'aws:ResourceTag/status': 'enabled'
```

Because IAM conditions are evaluated server-side by AWS at call time, this cannot be bypassed
by any client-side configuration change. A profile tagged `status=disabled` causes every
`InvokeModel` call to return `AccessDeniedException`, regardless of whether the client has
quota checking configured.

### Components

#### `deployment/infrastructure/lambda-functions/quota_enforcer/index.py` (new)

Runs every 5 minutes via EventBridge (same cadence as `MetricsAggregator`):

1. Reads the default quota policy from `QuotaPolicies` DynamoDB table
2. Lists all APPLICATION inference profiles and groups them by `user.email` tag
3. For each user, reads `UserQuotaMetrics` to get current monthly and daily token usage
4. Tags each profile `status=enabled` or `status=disabled` based on quota compliance
5. Only acts when `enforcement_mode=block`; alert-only policies are left unchanged

#### `deployment/infrastructure/quota-monitoring.yaml`

Added:
- `QuotaEnforcerRole` — IAM role with `bedrock:ListInferenceProfiles`, `bedrock:ListTagsForResource`,
  `bedrock:TagResource`, and DynamoDB read access to `UserQuotaMetrics` and `QuotaPolicies`
- `QuotaEnforcerFunction` — Lambda running `quota_enforcer/index.py`
- `QuotaEnforcerScheduleRule` — EventBridge rule, `rate(5 minutes)`
- `QuotaEnforcerFunctionArn` output

#### `deployment/infrastructure/lambda-functions/inference_profile_provisioner/index.py`

`_build_tags()` now adds `{"key": "status", "value": "enabled"}` to every newly created
inference profile. New profiles are enabled by default; `QuotaEnforcer` disables them only
if the user is already over quota at provisioning time (next enforcer run within 5 minutes).

#### `deployment/infrastructure/bedrock-auth-auth0.yaml`
#### `deployment/infrastructure/bedrock-auth-okta.yaml`
#### `deployment/infrastructure/bedrock-auth-cognito-pool.yaml`

`AllowBedrockInvokeOwnApplicationProfiles` IAM statement updated to add the `status` tag
condition in all three stacks. The Okta stack also received the full
`AllowBedrockInvokeOwnApplicationProfiles` statement which it previously lacked.

### Enforcement Timeline

```
User makes Bedrock call (tokens consumed)
  → AWS/Bedrock CloudWatch metric emitted
  → up to 7 min: BedrockMetricsBridge writes to /aws/claude-code/metrics
  → +5 min: MetricsAggregator updates UserQuotaMetrics
  → up to 5 min: QuotaEnforcer reads UserQuotaMetrics and tags profiles
  
Worst-case enforcement lag: ~17 minutes after quota is exceeded
Every subsequent Bedrock call returns AccessDeniedException immediately
```

### Deployment Steps

1. Tag existing inference profiles `status=enabled` before deploying the IAM change
   (otherwise they will be blocked until the first enforcer run):
   ```bash
   for arn in $(aws bedrock list-inference-profiles \
       --type-equals APPLICATION --region eu-central-1 \
       --query 'inferenceProfileSummaries[].inferenceProfileArn' --output text); do
     aws bedrock tag-resource --resource-arn "$arn" \
       --tags '[{"key":"status","value":"enabled"}]' --region eu-central-1
   done
   ```

2. Deploy the quota stack to create the enforcer Lambda:
   ```bash
   ccwb deploy quota
   ```

3. Deploy the auth stack to activate the IAM condition:
   ```bash
   ccwb deploy auth
   ```

### Security Comparison

| Threat | Client-side check only | Tag-based enforcement |
|---|---|---|
| User removes `quota_api_endpoint` from config | Bypasses quota entirely | No effect — IAM blocks at call time |
| Stale cached credentials (up to 30 min) | User keeps working past quota | Blocked within ~17 min regardless |
| User with stolen valid credentials | Quota check skipped if no config | Profile tagged disabled, all calls fail |
| Admin error (enforcer not deployed) | Same as before | Falls back to client-side check |

#### Alternative: Lambda Proxy (for direct federation)

If Cognito Identity Pool is not an option and direct federation is required, add a Lambda
that:

1. Validates the Entra JWT
2. Extracts `email` and `sub` claims
3. Calls `AssumeRoleWithWebIdentity` server-side using a custom-built JWT that includes
   the `https://aws.amazon.com/tags` claim
4. Returns short-lived credentials to the client

This adds operational complexity and is only recommended when the Cognito path is not
available.

---

## Code Changes Summary

### New Files

| File | Type | Purpose |
|------|------|---------|
| `deployment/infrastructure/lambda-functions/inference_profile_provisioner/index.py` | Lambda | Sole principal with Bedrock management permissions. Creates per-user Application Inference Profiles idempotently on login. Enforces canonical naming and tag schema server-side. |
| `deployment/infrastructure/lambda-functions/quota_enforcer/index.py` | Lambda | Runs every 5 min. Reads DynamoDB quotas, checks per-user usage, tags profiles `status=enabled` or `status=disabled`. Provides server-side enforcement that cannot be bypassed client-side. |
| `deployment/infrastructure/lambda-functions/bedrock_metrics_bridge/index.py` | Lambda | Bridges Bedrock CloudWatch metrics (InputTokenCount, OutputTokenCount, CacheRead, CacheWrite) into the OTEL-compatible log group (`/aws/claude-code/metrics`) every 5 min with a 2-min lookback. |
| `source/claude_code_with_bedrock/cli/commands/profiles.py` | CLI command | New `ccwb profiles list` and `ccwb profiles set-default <model>` commands. Lists profile ARNs from local cache or AWS, updates `~/.claude.json` with chosen ARN. |
| `source/tests/cli/commands/test_profiles.py` | Tests | 35 unit tests covering profile cache path, load/save, `~/.claude.json` read/write helpers. |
| `source/tests/test_inference_profile_models.py` | Tests | 59 tests for `INFERENCE_PROFILE_MODELS` config constants, ARN generation, profile naming, and tag building. |
| `source/tests/test_inference_profiles.py` | Tests | 54 integration tests with parametrized scenarios for profile name collision resistance, email sanitization, and region substitution. |
| `.kiro/steering/product.md` | Docs | Product overview for IT admins — architecture, monitoring configurations, ABAC isolation. |
| `.kiro/steering/structure.md` | Docs | Directory layout reference including Lambda naming conventions and inference profile provisioner role. |
| `.kiro/steering/tech.md` | Docs | Tech stack, build system, code style, and complete CLI command reference. |
| `CHANGES-CLOUDWATCH.md` | Docs | CloudWatch integration change log. |
| `CHANGES-INFERENCEPROFILE.md` | Docs | This file — authoritative migration design document. |
| `source/uv.lock` | Config | UV package manager stub (`requires-python = ">=3.14"`). |

---

### Modified Files

#### Lambda Functions

| File | Change type | What changed & why |
|------|-------------|---------------------|
| `deployment/infrastructure/lambda-functions/metrics_aggregator/index.py` | Bug fix | Time unit fix: CloudWatch Logs Insights requires seconds, not milliseconds. Fixed regex escaping for `"groups":\[`. Added ISO timestamp debug logging. |

#### CloudFormation Infrastructure

| File | Change type | What changed & why |
|------|-------------|---------------------|
| `deployment/infrastructure/bedrock-auth-auth0.yaml` | Major addition | New `InferenceProfilesEnabled` parameter. When true: switches IAM from direct model invocation to ABAC-gated inference profile invocation (`user.email` tag + `status=enabled` required). Inlines provisioner Lambda. Expands `ConfigurationJson` output to 4 variants. |
| `deployment/infrastructure/bedrock-auth-cognito-pool.yaml` | Major addition | Same as auth0.yaml but for Cognito User Pool federation path. |
| `deployment/infrastructure/bedrock-auth-okta.yaml` | Minor addition | Adds inference profile ABAC IAM conditions for Okta. Adds previously missing `AllowBedrockInvokeOwnApplicationProfiles` statement. |
| `deployment/infrastructure/cognito-identity-pool.yaml` | Moderate addition | Splits Bedrock invoke policy into shared vs user-specific. Adds `AllowCreateOwnApplicationProfiles` + `AllowTagOwnApplicationProfiles`. Updates `PrincipalTags` mapping (`email: email`, `sub: sub`). |
| `deployment/infrastructure/otel-collector.yaml` | Major addition | New `FilterTokenMetrics` parameter. When true, OTEL drops `claude_code.token.usage` and `claude_code.cost.usage` to prevent double-counting when inference profiles are also deployed. |
| `deployment/infrastructure/claude-code-dashboard.yaml` | Moderate addition | Adds `BedrockMetricsBridge` Lambda + EventBridge schedule (5-min cadence). Reads `AWS/Bedrock` namespace metrics and writes to OTEL log group for unified dashboard. |
| `deployment/infrastructure/quota-monitoring.yaml` | Moderate addition | Adds `QuotaEnforcer` Lambda, `QuotaEnforcerRole`, and `QuotaEnforcerScheduleRule` (5-min cadence). Standardizes all Lambda names to `ClaudeCode-*` prefix. |
| `deployment/infrastructure/landing-page-distribution.yaml` | Bug fix + feature | Fixes ALB log bucket policy (correct service principal). Adds `ExistingCertificateArn` parameter to skip ACM creation. Adds `DeletionPolicy: Retain` to ALB logs bucket. Fixes S3 client region configuration in Lambda. |

#### CLI Commands

| File | Change type | What changed & why |
|------|-------------|---------------------|
| `source/claude_code_with_bedrock/cli/__init__.py` | Minor addition | Registers `ProfilesListCommand` and `ProfilesSetDefaultCommand`. |
| `source/claude_code_with_bedrock/cli/commands/deploy.py` | Major refactor | Decouples `otel_enabled` from `monitoring_enabled`. Inference-profiles-only mode skips VPC/OTEL, deploys dashboard + quota + S3 bucket. Captures provisioner Lambda ARN from stack outputs. Writes default quota policy to DynamoDB on deploy. |
| `source/claude_code_with_bedrock/cli/commands/init.py` | Major addition | Setup wizard now treats inference profiles and OTEL as independent choices. New questions: inference profile model selection, existing ACM cert ARN. VPC question only shown when OTEL enabled. |
| `source/claude_code_with_bedrock/cli/commands/package.py` | Major addition | Adds shiv `.pyz` bundle support alongside PyInstaller. Docker-based cross-platform shiv builds. Install script detects `.pyz`, generates wrapper shell scripts, runs `--setup-profiles` on install when inference profiles enabled. |
| `source/claude_code_with_bedrock/cli/commands/destroy.py` | Minor addition | Skips OTEL stacks when `otel_enabled=false`. Falls back to `monitoring_enabled` for backward compatibility. |
| `source/claude_code_with_bedrock/cli/commands/distribute.py` | Bug fix | Fixed binary detection to handle both PyInstaller and shiv `.pyz` variants. |
| `source/claude_code_with_bedrock/cli/utils/aws.py` | Minor fix | `get_stack_outputs()` silently returns `{}` on `ValidationError` (stack doesn't exist) instead of printing noise. |
| `source/claude_code_with_bedrock/cli/commands/builds.py` | Formatting | Line wrapping only (ruff). |
| `source/claude_code_with_bedrock/cli/commands/test.py` | Formatting | Line wrapping only (ruff). |

#### Core Logic

| File | Change type | What changed & why |
|------|-------------|---------------------|
| `source/claude_code_with_bedrock/models.py` | Major addition | New `INFERENCE_PROFILE_MODELS` dict (opus-4-6, sonnet-4-6, haiku-4-5 with cross-region ARN templates). New helpers: `get_enabled_inference_profile_models()`, `get_inference_profile_source_arn()`, `get_application_profile_name()`, `get_application_profile_tags()`. |
| `source/claude_code_with_bedrock/config.py` | Minor addition | New `Profile` fields: `inference_profiles_enabled`, `inference_profiles_models`, `inference_profiles_default_model`, `inference_profiles_provisioner_arn`, `distribution_certificate_arn`. |
| `source/claude_code_with_bedrock/quota_policies.py` | Formatting | Ruff auto-formatting only — no logic changes. |

#### Credential Provider

| File | Change type | What changed & why |
|------|-------------|---------------------|
| `source/credential_provider/__main__.py` | Major addition | After credential exchange, invokes provisioner Lambda to create profiles and caches ARNs locally. Patches `~/.claude.json` (default model ARN) and `~/.claude/settings.json` (all model env vars). New `--setup-profiles` CLI flag for manual setup during installation. |

#### Tests

| File | Change type | What changed & why |
|------|-------------|---------------------|
| `source/tests/test_confidential_client.py` | Formatting | Import ordering and context manager reformatting (ruff/black). |
| `source/tests/test_silent_refresh.py` | Formatting | Import ordering and context manager reformatting (ruff/black). |

#### Dependencies & Documentation

| File | Change type | What changed & why |
|------|-------------|---------------------|
| `source/pyproject.toml` | Version bump + dependency | `2.3.0` → `2.4.0`. Added `shiv = "^1.0.0"` for `.pyz` bundle support. |
| `source/poetry.lock` | Dependency update | Poetry `2.2.1` → `2.3.3`. Removed transitive packages (`backports.tarfile`, `jaraco-context`, `jaraco-functools`) cleaned up by Poetry 2.3. |
| `README.md` | Major addition | New section on per-user CloudWatch monitoring with inference profiles (~230 lines). Covers ABAC config per IdP, coexistence guidance, cost alarm examples. |
| `CHANGELOG.md` | Release notes | v2.4.0 release notes documenting all new features. |
| `.gitignore` | Minor addition | Added `.kiro/` and `source/credential_provider/config.json` exclusions. Fixed test file pattern to root-level only. |
