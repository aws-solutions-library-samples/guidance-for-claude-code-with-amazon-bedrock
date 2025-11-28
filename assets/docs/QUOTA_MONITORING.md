# Claude Code Quota Monitoring

Quota monitoring tracks user token consumption and sends automated alerts when usage thresholds are exceeded, helping administrators manage costs and prevent unexpected overages.

## Overview

The quota monitoring system is an optional CloudFormation stack that integrates with the dashboard stack to track monthly token consumption per user and send SNS alerts at configurable thresholds.

### Key Features

- **Per-user token tracking**: Monthly and daily consumption monitoring for each authenticated user
- **Fine-grained quota policies**: Set limits at user, group, or default levels with precedence rules
- **Multiple limit types**: Monthly tokens, daily tokens, and cost-based limits (USD)
- **Configurable thresholds**: Alerts at 80%, 90%, and 100% of limits
- **Cost estimation**: Track estimated costs based on Bedrock pricing per model
- **JWT group integration**: Automatically extract group membership from identity provider claims
- **Alert deduplication**: One alert per threshold per limit type per user per period
- **DynamoDB storage**: Efficient tracking with automatic TTL cleanup

### Architecture Components

- **UserQuotaMetrics Table**: DynamoDB table storing monthly/daily usage totals with token type breakdown
- **QuotaPolicies Table**: DynamoDB table storing fine-grained quota policies (user/group/default)
- **Quota Monitor Lambda**: Scheduled function checking thresholds every 15 minutes
- **SNS Topic**: Alert delivery to administrators
- **EventBridge Rule**: Lambda scheduling
- **Metrics Aggregator Integration**: Updates quota table during metric processing with cost calculation

## Configuration

> **Prerequisites**: Monitoring must be enabled and the dashboard stack deployed. See the [CLI Reference](CLI_REFERENCE.md#deploy---deploy-infrastructure) for deployment details.

During `ccwb init`, quota monitoring is **enabled by default** when monitoring is enabled. You'll be prompted to configure:
- Monthly token limit per user (default: 10 million tokens)
- Automatic threshold calculation (80% warning at 8M, 90% critical at 9M)
- Daily token limit with burst buffer (auto-calculated from monthly)
- Enforcement modes for daily and monthly limits

Deploy using `poetry run ccwb deploy` (deploys all enabled stacks) or `poetry run ccwb deploy quota` for just the quota stack. The OIDC configuration is automatically passed from your profile settings. For complete deployment instructions, see the [CLI Reference](CLI_REFERENCE.md#deploy---deploy-infrastructure).

## Configuration Settings

| Parameter               | Default     | Description                                    |
| ----------------------- | ----------- | ---------------------------------------------- |
| MonthlyTokenLimit       | 10M tokens  | Default maximum per user per month             |
| DailyTokenLimit         | ~367K tokens| Daily limit (auto-calculated with burst buffer)|
| BurstBufferPercent      | 10%         | Daily buffer for usage variation (5-25%)       |
| MonthlyEnforcementMode  | block       | Block access when monthly limit exceeded       |
| DailyEnforcementMode    | alert       | Alert only when daily limit exceeded           |
| Warning Threshold       | 80% (8M)    | First alert level                              |
| Critical Threshold      | 90% (9M)    | Second alert level                             |
| Check Frequency         | 15 minutes  | Lambda execution interval                      |
| Alert Retention         | 60 days     | DynamoDB TTL for deduplication                 |
| EnableFinegrainedQuotas | true        | Enable fine-grained policy support             |

To update limits: Re-run `ccwb init` and redeploy with `ccwb deploy quota`.

## Daily Limits and Bill Shock Protection

To prevent unexpected costs from runaway usage, the system auto-calculates a daily limit from your monthly quota with a configurable burst buffer.

### Why Daily Limits?

Without daily limits, a user could consume their entire monthly quota in just 2-3 days of heavy usage, leading to unexpected costs or blocked access mid-month. Daily limits catch runaway usage within 24 hours while still allowing legitimate work patterns.

### Calculation

```
daily_limit = monthly_limit ÷ 30 × (1 + burst_buffer%)
```

Example with 10M monthly limit and 10% burst:
- Base daily: 10,000,000 ÷ 30 = 333,333 tokens/day
- With 10% burst: 333,333 × 1.10 = **366,667 tokens/day**

### Burst Buffer Guidance

The burst buffer allows for legitimate daily variation above the average:

| Buffer | Daily (10M/month) | Use Case |
|--------|-------------------|----------|
| 5% (strict)  | 350,000 tokens | Tight cost control, heavy days blocked quickly |
| 10% (default)| 366,667 tokens | Balanced protection for typical usage |
| 25% (flexible)| 416,667 tokens | Allows 1.25x average days, catches only extreme spikes |

### Enforcement Modes

Each limit type can be configured with different enforcement:

| Mode | Behavior | Use Case |
|------|----------|----------|
| **alert** | Send notifications, allow continued use | Monitoring, soft limits |
| **block** | Deny credential issuance when exceeded | Hard cost control |

**Recommended defaults:**
- **Daily**: `alert` - Warn about unusual patterns, don't interrupt work
- **Monthly**: `block` - Hard stop at budget limit

### Example Configuration

```
Monthly Limit: 10,000,000 tokens (block)
Daily Limit:   366,667 tokens (alert)
Burst Buffer:  10%

Behavior:
- Day 1: User consumes 400K tokens → Daily alert sent
- Day 2: User consumes 380K tokens → Daily alert sent
- Day 3-5: Normal usage (~300K/day) → No alerts
- Day 15: Monthly usage reaches 8M → 80% warning alert
- Day 20: Monthly usage reaches 10M → Access blocked
```

## Fine-Grained Quota Policies

Fine-grained quotas allow administrators to set different limits for different users and groups, with a clear precedence hierarchy.

### Policy Types

1. **User Policies**: Apply to a specific user by email address
2. **Group Policies**: Apply to all users in a group (from JWT claims)
3. **Default Policy**: Applies to all users without a more specific policy

### Policy Precedence

When determining the effective quota for a user:

1. **User-specific policy** (highest priority): If a policy exists for the user's email, use it
2. **Group policy** (most restrictive): If user belongs to multiple groups with policies, use the **lowest limit** (most restrictive)
3. **Default policy**: If no user or group policy applies, use the default
4. **No policy**: If no policies are defined, usage is **unlimited** (quota monitoring disabled for that user)

### Limit Types

Each policy can configure three types of limits:

| Limit Type           | Description                        | Reset Period     |
| -------------------- | ---------------------------------- | ---------------- |
| Monthly Token Limit  | Maximum tokens per calendar month  | 1st of each month|
| Daily Token Limit    | Maximum tokens per day             | UTC midnight     |
| Monthly Cost Limit   | Maximum estimated cost in USD      | 1st of each month|

### Managing Policies with CLI

Use the `ccwb quota` commands to manage policies:

```bash
# Set a user-specific policy
ccwb quota set-user john.doe@company.com --monthly-limit 500M --daily-limit 20M

# Set a group policy
ccwb quota set-group engineering --monthly-limit 400M --cost-limit 600.00

# Set the default policy for all users
ccwb quota set-default --monthly-limit 10M --daily-limit 500K --cost-limit 200.00

# List all policies
ccwb quota list
ccwb quota list --type group

# Show effective policy for a user
ccwb quota show john.doe@company.com --groups "engineering,ml-team"

# View current usage against limits
ccwb quota usage john.doe@company.com

# Delete a policy
ccwb quota delete group engineering

# Temporarily unblock a user who exceeded quota (Phase 2)
ccwb quota unblock john.doe@company.com --duration 24h
```

### Token Value Shortcuts

The CLI supports human-readable token values:

- `10M` = 10,000,000 (10 million) - default limit
- `500K` = 500,000 (500 thousand)
- `1B` = 1,000,000,000 (1 billion)

### Group Membership from JWT Claims

The system automatically extracts group membership from JWT token claims:

- `groups`: Standard groups claim
- `cognito:groups`: Amazon Cognito groups
- `custom:department`: Custom department claim (treated as a group)

Configure your identity provider to include group claims in the JWT tokens issued to users.

## Cost Estimation

The system tracks token usage by type and estimates costs based on Bedrock pricing:

| Model                            | Input/1M | Output/1M | Cache Read/1M |
| -------------------------------- | -------- | --------- | ------------- |
| Claude Sonnet 4.5                | $3.00    | $15.00    | $0.30         |
| Claude Opus 4.5                  | $15.00   | $75.00    | $1.50         |

Cost estimates are calculated automatically as usage occurs and included in alerts.

## Alert Management

After deployment, subscribe to the SNS topic for notifications:

```bash
# Get topic ARN from stack outputs
aws cloudformation describe-stacks --stack-name <quota-stack-name> \
  --query 'Stacks[0].Outputs[?OutputKey==`QuotaAlertTopicArn`].OutputValue' \
  --output text

# Subscribe (email, SMS, HTTPS webhook, etc.)
aws sns subscribe --topic-arn <arn> --protocol email --notification-endpoint admin@company.com
```

### Alert Types

The system sends alerts for three limit types, each with three threshold levels:

#### Monthly Token Alert

Sent when monthly token usage exceeds 80%, 90%, or 100% of the monthly limit.

#### Daily Token Alert

Sent when daily token usage exceeds 80%, 90%, or 100% of the daily limit. Daily alerts can be sent each day (they include the date in the deduplication key).

#### Cost Alert

Sent when estimated monthly cost exceeds 80%, 90%, or 100% of the cost limit.

### Sample Alert Content

```
Subject: Claude Code CRITICAL - Monthly Token Quota - 92%

Claude Code Usage Alert - Monthly Token Quota

User: john.doe@company.com
Alert Level: CRITICAL
Month: November 2025
Policy: group:engineering

Current Usage: 9,200,000 tokens
Monthly Limit: 10,000,000 tokens
Percentage Used: 92.0%

Days Remaining in Month: 8
Daily Average: 418,182 tokens
Projected Monthly Total: 12,545,460 tokens

Estimated Cost So Far: $138.00

---
This alert is sent once per threshold level per month.
```

Alerts are deduplicated - each threshold triggers only once per user per period, with history stored in DynamoDB (60-day TTL).

## Troubleshooting

### Quick Checks

```bash
# View Lambda logs
aws logs tail /aws/lambda/claude-code-quota-monitor --follow

# Query user quotas
aws dynamodb scan --table-name UserQuotaMetrics \
  --projection-expression "email, total_tokens, daily_tokens, estimated_cost"

# List quota policies
aws dynamodb scan --table-name QuotaPolicies \
  --filter-expression "sk = :current" \
  --expression-attribute-values '{":current": {"S": "CURRENT"}}'
```

### Common Issues

- **No alerts**: Verify SNS subscriptions are confirmed and EventBridge rule is enabled
- **Missing users**: Check JWT tokens include email claim
- **Wrong policy applied**: Verify group claims are present in JWT tokens
- **Groups not detected**: Check that `ENABLE_FINEGRAINED_QUOTAS` is set to `true`
- **Cost estimates off**: Token type breakdown requires OTEL metrics to include `type` field

For detailed monitoring setup, see the [Monitoring Guide](MONITORING.md).

## Cost Considerations

**Estimated monthly costs for <1000 users: $2-10**
- Lambda: ~2,880 invocations x $0.0000002 = $0.58
- DynamoDB: Pay-per-request for user count x 2,880 operations
- SNS: $0.50 per million notifications
- CloudWatch Logs: Standard retention pricing
- QuotaPolicies table: Minimal cost (policies rarely change)

## Data Schema

### UserQuotaMetrics Table

**User Totals**: `PK: USER#{email}`, `SK: MONTH#{YYYY-MM}`
- Attributes: `total_tokens`, `daily_tokens`, `daily_date`, `input_tokens`, `output_tokens`, `cache_tokens`, `estimated_cost`, `groups`, `last_updated`, `email`
- TTL: End of following month

**Alert History**: `PK: ALERTS`, `SK: {YYYY-MM}#ALERT#{email}#{type}#{level}[#{date}]`
- Attributes: `sent_at`, `alert_type`, `alert_level`, `usage_at_alert`, `policy_info`
- TTL: 60 days

### QuotaPolicies Table

**Policy Records**: `PK: POLICY#{type}#{identifier}`, `SK: CURRENT`
- Attributes: `policy_type`, `identifier`, `monthly_token_limit`, `daily_token_limit`, `monthly_cost_limit`, `warning_threshold_80`, `warning_threshold_90`, `enforcement_mode`, `enabled`, `created_at`, `updated_at`, `created_by`

**GSI: PolicyTypeIndex**
- PK: `policy_type` (user, group, default)
- SK: `identifier`
- Enables efficient queries like "list all group policies"

## Migration from Basic Quotas

If you're upgrading from the basic quota system (single global limit):

1. Deploy the updated CloudFormation stack (adds QuotaPolicies table)
2. Existing UserQuotaMetrics data continues working (new fields are nullable)
3. Set `EnableFinegrainedQuotas: true` in stack parameters
4. Optionally create a default policy to maintain previous behavior:
   ```bash
   ccwb quota set-default --monthly-limit 10M
   ```
5. Gradually add group/user policies as needed

**No breaking changes** - this is an enhancement that's opt-in through policy creation.

## Access Blocking (Phase 2)

When `enforcement_mode` is set to `"block"` for a policy, the system will deny credential issuance when a user exceeds their quota limits.

### How Blocking Works

1. **Quota Check API**: A real-time API endpoint checks user quota before credential issuance
2. **Enforcement Point**: The credential provider calls the quota check API after OIDC authentication
3. **Block Triggers**: Access is blocked when:
   - Monthly token usage ≥ monthly_token_limit
   - Daily token usage ≥ daily_token_limit (if configured)
   - Estimated cost ≥ monthly_cost_limit (if configured)

### Configuring Blocking

Enable blocking for a policy:

```bash
# Set user policy with blocking enabled
ccwb quota set-user john.doe@company.com --monthly-limit 10M --enforcement block

# Set group policy with blocking
ccwb quota set-group engineering --monthly-limit 50M --enforcement block

# Set default with blocking
ccwb quota set-default --monthly-limit 10M --enforcement block
```

### Admin Override (Unblock)

Administrators can temporarily unblock users who have exceeded their quota:

```bash
# Unblock for 24 hours (default)
ccwb quota unblock john.doe@company.com

# Unblock for 7 days
ccwb quota unblock john.doe@company.com --duration 7d

# Unblock until end of month (quota reset)
ccwb quota unblock john.doe@company.com --duration until-reset

# With reason
ccwb quota unblock john.doe@company.com --duration 24h --reason "Urgent project deadline"
```

The unblock record expires automatically and is cleaned up by DynamoDB TTL.

### Error Handling: Fail-Open vs Fail-Closed

By default, the system uses **fail-open** behavior - if the quota check API is unavailable, access is allowed. This prevents service disruptions due to network issues.

Configure fail mode in your profile config:

```json
{
  "quota_fail_mode": "open"   // Allow on error (default)
  // OR
  "quota_fail_mode": "closed" // Deny on error (stricter)
}
```

The 15-minute Lambda monitoring job continues to run regardless, so alerts will still be sent even if real-time checks fail.

### Quota Check API

The Quota Check API is a secured HTTP endpoint that validates user quotas before credential issuance.

#### API Security

The API requires JWT authentication using your OIDC provider's tokens:

- **Authentication**: JWT token in `Authorization: Bearer <token>` header
- **Validation**: API Gateway JWT Authorizer validates the token against your OIDC provider
- **User Identity**: Email and group membership extracted from validated JWT claims (no query parameters)

This ensures:
- Only authenticated users can check quotas
- User identity cannot be spoofed (claims come from validated JWT)
- No additional credentials needed (uses same OIDC token from auth flow)

#### Deployment Configuration

When using `ccwb deploy quota`, the OIDC configuration is **automatically passed** from your profile settings (configured during `ccwb init`). No manual parameter configuration is required.

For manual CloudFormation deployments, provide your OIDC configuration:

```bash
aws cloudformation deploy \
  --stack-name claude-code-quota \
  --template-file quota-monitoring.yaml \
  --parameter-overrides \
    OidcIssuerUrl="https://company.okta.com" \
    OidcClientId="your-client-id" \
    # ... other parameters
```

The OIDC parameters must match your credential provider configuration:
- `OidcIssuerUrl`: Your identity provider's issuer URL (e.g., `https://company.okta.com` for Okta)
- `OidcClientId`: The client ID configured in your identity provider

After deploying, get the API endpoint from stack outputs:

```bash
# Get quota check API endpoint
aws cloudformation describe-stacks --stack-name <quota-stack-name> \
  --query 'Stacks[0].Outputs[?OutputKey==`QuotaCheckApiEndpoint`].OutputValue' \
  --output text
```

Configure the endpoint in your credential provider config.json:

```json
{
  "profiles": {
    "ClaudeCode": {
      "quota_api_endpoint": "https://xxx.execute-api.us-east-1.amazonaws.com"
    }
  }
}
```

#### API Responses

| Scenario | HTTP Status | Response |
|----------|-------------|----------|
| No/invalid JWT | 401 | Unauthorized (API Gateway rejects) |
| Valid JWT, quota OK | 200 | `{"allowed": true, ...}` |
| Valid JWT, quota exceeded | 200 | `{"allowed": false, "reason": "monthly_exceeded", ...}` |
| Valid JWT, missing email claim | 200 | `{"allowed": true, "reason": "missing_email_claim"}` (fail-open) |

### Enforcement Timing

**Important**: Quota enforcement only occurs at credential issuance time, not during an active session.

If a user exceeds their quota mid-session, they can continue using Claude Code until their credentials expire and they need to re-authenticate. At that point, the quota check will block access.

#### Example Timeline (12-hour session)

```
09:00 - User authenticates, quota check passes (at 50% of limit)
09:00 - AWS credentials issued, valid for 12 hours
15:00 - User exceeds 100% of monthly quota
15:01 - User CONTINUES working (credentials still valid)
21:00 - Credentials expire, user must re-authenticate
21:00 - Quota check BLOCKS access (enforcement finally applied)
```

In this scenario, there's a 6-hour gap between exceeding the quota (15:00) and enforcement (21:00).

#### Recommendation for Tight Enforcement

Reduce `max_session_duration` when blocking is enabled:

| Session Duration | Enforcement Gap | Use Case |
|------------------|-----------------|----------|
| 12h (default) | Up to 12 hours | Alert-only mode |
| 4h | Up to 4 hours | Moderate enforcement |
| 1h (recommended) | Up to 1 hour | Strict cost control |

Configure in your profile:

```json
{
  "profiles": {
    "ClaudeCode": {
      "max_session_duration": 3600,
      "quota_api_endpoint": "https://xxx.execute-api.us-east-1.amazonaws.com"
    }
  }
}
```

**Trade-off**: Shorter sessions mean more frequent re-authentication prompts for users, but provide tighter quota enforcement.

## Current Limitations

- Quotas reset on calendar month/day (UTC timezone)
- Requires email claim in JWT tokens
- Group membership requires JWT group claims from identity provider
- Cost estimates are approximate (based on token counts and model pricing)
- Enforcement only at credential issuance (see [Enforcement Timing](#enforcement-timing) for mitigation)

## Future Enhancements

- **Bulk import/export**: Manage policies via JSON files
- **Quota reporting**: Generate usage reports across all users

## Integration Points

- **Dashboard**: Shares DynamoDB metrics table and OTEL pipeline
- **Analytics**: Quota data available in Athena queries (see [Analytics Guide](ANALYTICS.md))
- **External Systems**: SNS topic supports webhooks, Lambda triggers, and third-party integrations
- **Identity Provider**: Group membership extracted from JWT claims

For complete monitoring setup and general telemetry information, see the [Monitoring Guide](MONITORING.md).
