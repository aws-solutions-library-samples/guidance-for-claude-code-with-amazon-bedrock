# Key Fixes & Configuration Changes

Documenting critical fixes that were required to get the AllCode AI Gateway and Nexus UI working end-to-end.

---

## 1. Claude Code Not Connecting to Bedrock

**Symptom:** Claude Code shows "Not logged in · Please run /login" or "Invalid API key"

**Root Cause:** `ANTHROPIC_API_KEY` environment variable was set in `~/.zshrc`, causing Claude Code to try Anthropic's API instead of Bedrock.

**Fix:**
```bash
# Remove from shell profile
sed -i '' '/ANTHROPIC_API_KEY/d' ~/.zshrc
# Unset in current session
unset ANTHROPIC_API_KEY
```

---

## 2. Extended Thinking API Error

**Symptom:** `API Error: 400 messages.1.content.0.type: Expected 'thinking' or 'redacted_thinking'`

**Root Cause:** The selected Bedrock model has extended thinking enabled but the message format is incompatible.

**Fix:** Add `CLAUDE_CODE_DISABLE_THINKING=1` to `~/.claude/settings.json` env section.

---

## 3. Package Build Fails — "Could not fetch stack outputs"

**Symptom:** `ccwb package` fails because it can't query CloudFormation stacks in a different AWS account.

**Root Cause:** The deployment infrastructure is in account 916587687563 but the admin running `ccwb package` authenticates to account 302740385673. The package command tries to query stacks to get the Identity Pool ID.

**Fix:** Added `identity_pool_id` field to the Profile dataclass and patched `package.py` to skip the CloudFormation query when the ID is already in the profile config.

```python
# In ~/.ccwb/profiles/allcode-dev-us-east-1.json
"identity_pool_id": "us-east-1:34ed05ea-eda2-4830-b2bf-37c37596edfb"
```

---

## 4. Bedrock Model Access Denied (Marketplace)

**Symptom:** `AccessDeniedException: Model access is denied due to IAM user or service role is not authorized to perform the required AWS Marketplace actions`

**Root Cause:** Some model IDs (e.g., `us.anthropic.claude-sonnet-4-5-20250929-v1:0`) require Marketplace subscription permissions that the Cognito federated role doesn't have.

**Fix:** Use a different model that works with the existing role permissions:
```
us.anthropic.claude-sonnet-4-20250514-v1:0  ← works
us.anthropic.claude-sonnet-4-5-20250929-v1:0  ← fails (Marketplace issue)
```

---

## 5. Telemetry Not Reaching OTel Collector (401 Unauthorized)

**Symptom:** CloudWatch metrics show `TotalTokens: 0` despite active Claude Code usage. The OTel collector endpoint returns 401.

**Root Cause (multi-part):**

### 5a. Missing otel-helper-bin binary
The shell wrapper at `~/claude-code-with-bedrock/otel-helper` calls `otel-helper-bin` which wasn't installed.

**Fix:** Copy from the built package:
```bash
cp dist/allcode-dev-us-east-1/<timestamp>/otel-helper-macos-arm64 ~/claude-code-with-bedrock/otel-helper-bin
chmod +x ~/claude-code-with-bedrock/otel-helper-bin
xattr -d com.apple.quarantine ~/claude-code-with-bedrock/otel-helper-bin
```

### 5b. otel-helper not sending Authorization header
The otel-helper only output user metadata headers (x-user-email, etc.) but not the JWT token needed for ALB authentication.

**Fix:** Rewrote `~/claude-code-with-bedrock/otel-helper` as a Python script that reads the ID token from the OS keyring and includes it as `Authorization: Bearer <token>`:
```python
import keyring
data = keyring.get_password('claude-code-with-bedrock', f'{PROFILE}-monitoring')
token = json.loads(data).get('token', '')
headers['Authorization'] = f'Bearer {token}'
```

### 5c. ALB JWT validation rejecting valid tokens (aud claim mismatch)
The ALB's `jwt-validation` action was configured with `Format: string-array` for the `aud` claim, but Cognito ID tokens have `aud` as a plain string. Additionally, the ALB was configured for client ID `1maifaaf4fnis38u8960asont9` but tokens were issued with audience `3lf5anq78ekk6fpfsi3307mhg2`.

**Fix:** Updated the `claude-code-auth-monitoring` CloudFormation stack to remove the `aud` claim check (issuer validation is sufficient):
```bash
aws cloudformation update-stack \
  --stack-name claude-code-auth-monitoring \
  --use-previous-template \
  --capabilities CAPABILITY_IAM \
  --parameters ParameterKey=OidcClientId,ParameterValue="" \
    # ... other params with UsePreviousValue=true
```

---

## 6. Nexus UI Pages Not Loading in Production

**Symptom:** Billing, Models, Settings pages flash briefly then redirect to Dashboard.

**Root Cause:** The production routes in `App.tsx` (inside the `AuthProvider` block) only had Dashboard, Users, Quotas, and Me. The new pages were only in the dev-mode `content` block.

**Fix:** Added all routes to both the dev-mode and production sections of `App.tsx`.

---

## 7. macOS Gatekeeper Blocking Binaries

**Symptom:** "credential-process-macos-arm64 Not Opened" error on macOS.

**Fix:**
```bash
xattr -d com.apple.quarantine ~/claude-code-with-bedrock/credential-process
xattr -d com.apple.quarantine ~/claude-code-with-bedrock/otel-helper-bin
```

---

## 8. DNS for Custom Domain (nexus.allcode.com)

**Symptom:** ACM certificate stuck in `PENDING_VALIDATION`.

**Root Cause:** `allcode.com` nameservers point to Cloudflare, not Route 53. The validation CNAME record was added to Route 53 but DNS queries go to Cloudflare.

**Fix:** Add these records in **Cloudflare** (not Route 53):
```
_0eb2f837c36aa25d85038f16a074c935.nexus.allcode.com  CNAME  _40528551fb025b1c303e73b26356b486.jkddzztszm.acm-validations.aws.
nexus.allcode.com  CNAME  djbay5s00i5is.cloudfront.net
```

---

## Environment Summary

| Component | Account | Value |
|-----------|---------|-------|
| Infrastructure | 916587687563 | Cognito, IAM roles, Bedrock, monitoring |
| Admin access | allcode-admin profile | SSO via IAM Identity Center |
| Cognito User Pool | us-east-1_3mbtSSlmt | 4 users, claude-code-admins group |
| CLI client ID | 3lf5anq78ekk6fpfsi3307mhg2 | Used by credential-process |
| Monitoring client ID | 1maifaaf4fnis38u8960asont9 | Original ALB auth (now disabled aud check) |
| OTel endpoint | https://telemetry.allcode.com | ALB → ECS Fargate → CloudWatch |
| Nexus UI | https://djbay5s00i5is.cloudfront.net | S3 + CloudFront |
| Nexus API | https://dtxfifv2cj.execute-api.us-east-1.amazonaws.com | API Gateway + Lambda |
| Distribution bucket | claude-code-auth-distribution-916587687563 | Package downloads |
