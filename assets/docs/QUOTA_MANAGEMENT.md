# Quota Management

This guide explains how the token quota system works, how quotas are evaluated and enforced, and what administrators and end users can expect. For CLI command reference, see the [Administrator Guide](ADMINISTRATOR_GUIDE.md). For the underlying infrastructure and DynamoDB schema, see [Quota Monitoring](QUOTA_MONITORING.md).

---

## How Quotas Work

Quotas limit how many tokens a user can consume across all Claude models over a given period. Limits are set as **monthly** and optionally **daily** token budgets. Token usage is **aggregated across all models** — there are no per-model limits. If a user consumes 100M tokens on Sonnet and 125M on Opus, their total is 225M regardless of which models were used.

Quotas are entirely server-side. They are stored in DynamoDB and evaluated by Lambda functions. Changing a quota policy takes effect immediately without rebuilding or redistributing user packages.

---

## Policy Hierarchy

When a user requests credentials, the system resolves their effective quota by checking three levels in order:

| Priority | Policy Type | Key | Example |
|----------|------------|-----|---------|
| 1 (highest) | **User** | Email address | `alice@company.com` → 300M/month |
| 2 | **Group** | JWT group claim | `engineering` → 500M/month |
| 3 (lowest) | **Default** | Global fallback | All users → 225M/month |

- If a **user-specific** policy exists, it wins unconditionally.
- If the user belongs to **multiple groups** with policies, the **most restrictive** (lowest monthly limit) applies.
- If no user or group policy matches, the **default** policy applies.
- If **no policies exist at all**, the user has unlimited access (quota system is effectively disabled for them).

Group membership is extracted from JWT token claims at authentication time. The system checks the `groups`, `cognito:groups`, and `custom:department` claims.

---

## When Quotas Are Evaluated

Quota checks happen at three points, not during active Bedrock API calls:

### 1. At credential issuance (per authentication)

After the user authenticates via OIDC, and before AWS credentials are returned, the credential provider calls the **Quota Check API** (Lambda behind API Gateway). If the user is over their limit and enforcement mode is `block`, no credentials are issued.

This is the primary enforcement point. See `credential_provider/__main__.py:1851-1860`.

### 2. Periodic re-check with cached credentials (default: every 30 minutes)

AWS credentials are cached for 8–12 hours. Without periodic re-checks, a user could continue working long after exceeding their quota. The credential provider tracks when it last checked and re-evaluates on subsequent credential requests if the configured interval has elapsed.

The default interval is 30 minutes. Setting it to `0` checks every request (~200ms overhead). Setting it to `60` checks hourly.

See `credential_provider/__main__.py:1795-1808`.

### 3. Scheduled monitoring (every 15 minutes)

An EventBridge rule triggers the `claude-code-quota-monitor` Lambda every 15 minutes. This scans all users' token usage in DynamoDB and sends SNS alerts to administrators when thresholds are crossed (80%, 90%, 100%). This runs independently of any user activity and is the mechanism that powers admin email/webhook alerts.

See `deployment/infrastructure/quota-monitoring.yaml:209-214`.

**Quotas are NOT evaluated during Bedrock API calls.** Claude Code calls Bedrock directly using the temporary AWS credentials. There is no API Gateway or proxy in the Bedrock request path. Enforcement only happens when the credential provider runs.

---

## Enforcement Modes

Each policy has an enforcement mode that determines what happens when a limit is exceeded:

| Mode | User experience | Credentials issued? | Use case |
|------|----------------|-------------------|----------|
| `alert` | Warning notification shown; work continues | Yes | Soft rollout, observing usage patterns |
| `block` | Access denied with usage breakdown; told to contact admin | No | Hard cost control |

The recommended default is `block` for monthly limits and `alert` for daily limits. This lets users have unusually heavy days without interruption while still enforcing a hard monthly budget.

---

## Enforcement Gap

Because enforcement happens at credential issuance — not during API calls — there is a gap between when a user exceeds their quota and when they are actually blocked:

```
09:00 — User authenticates, quota check passes (50% used)
09:00 — Credentials issued, valid for 12 hours
15:00 — User exceeds 100% of monthly quota
15:30 — Periodic re-check blocks further credential refreshes
         (or up to 21:00 if re-check is disabled and credentials haven't expired)
```

The periodic re-check (default 30 minutes) closes most of this gap. For tighter enforcement, reduce `quota_check_interval` to `0` (check every request) or reduce `max_session_duration` to shorten credential lifetime.

| Session duration | Re-check interval | Maximum enforcement delay |
|------------------|--------------------|--------------------------|
| 12h (default) | 30 min (default) | ~30 minutes |
| 12h | 0 (every request) | Immediate on next request |
| 1h | 30 min | ~30 minutes |
| 1h | 0 | Immediate on next request |

---

## What Users See

### Below 80% usage

Nothing. Credentials are issued silently.

### Warning (80–99% usage)

A terminal banner and browser notification appear showing current usage:

```
============================================================
QUOTA WARNING
============================================================
  Monthly: 180,000,000 / 225,000,000 tokens (80.0%)
  Daily: 6,600,000 / 8,250,000 tokens (80.0%)
============================================================
```

The browser page shows color-coded progress bars (green → yellow → orange). Access continues normally.

### Blocked (100%+ usage, enforcement mode = `block`)

Credentials are denied. The terminal shows:

```
============================================================
ACCESS BLOCKED - QUOTA EXCEEDED
============================================================

Monthly quota exceeded: 225,000,000 / 225,000,000 tokens (100.0%).
Contact your administrator for assistance.

Current Usage:
  Monthly: 225,000,000 / 225,000,000 tokens (100.0%)

Policy: user:alice@company.com

To request an unblock, contact your administrator.
============================================================
```

A browser page opens with a red status indicator. The credential provider exits with code 1, and Claude Code cannot make Bedrock calls.

---

## What Administrators See

The scheduled Lambda sends SNS alerts at each threshold crossing. Each alert includes:

- User email and the policy that triggered it
- Current usage and limit with percentage
- Days remaining in the month
- Daily average and projected monthly total
- The `ccwb quota unblock` command to run if needed

Alerts are deduplicated — each threshold (80%, 90%, 100%) triggers only once per user per period, stored in DynamoDB with a 60-day TTL.

---

## Daily Limits and Bill Shock Protection

Without daily limits, a user could burn their entire monthly budget in 2–3 days. Daily limits catch runaway usage within 24 hours.

Daily limits are auto-calculated from the monthly limit with a configurable burst buffer:

```
daily_limit = monthly_limit ÷ 30 × (1 + burst_buffer%)
```

For example, with a 225M monthly limit and 10% burst buffer:
- Base daily: 225M ÷ 30 = 7.5M
- With burst: 7.5M × 1.10 = **8.25M tokens/day**

| Burst buffer | Daily limit (225M/month) | Trade-off |
|-------------|-------------------------|-----------|
| 5% (strict) | 7.875M | Catches spikes fast; may interrupt heavy days |
| 10% (default) | 8.25M | Balanced |
| 25% (flexible) | 9.375M | Only catches extreme spikes |

Daily tokens reset at UTC midnight.

---

## Emergency Unblock

Administrators can temporarily restore access for blocked users:

```bash
ccwb quota unblock alice@company.com --duration 24h --reason "Project deadline"
```

Duration options: `1h` to `7d`, or `until-reset` (end of calendar month). The unblock is stored in DynamoDB with a TTL and checked by the Quota Check Lambda before evaluating limits. An audit trail records who unblocked, when, and why.

---

## Fail Mode

If the Quota Check API is unreachable (network issue, Lambda cold start timeout, etc.), the system's behavior depends on the configured fail mode:

| Mode | Behavior | Configuration |
|------|----------|---------------|
| `fail_closed` (default in Lambda) | Deny access | Safer for cost control |
| `open` | Allow access | Prevents service disruption |

The credential provider also has a client-side `quota_fail_mode` setting (`open` by default) that controls behavior when the API call itself fails. The 15-minute monitoring Lambda continues to run independently, so admin alerts are sent regardless of real-time check failures.

---

## Quota Check API Security

The Quota Check API is an HTTP endpoint (API Gateway + Lambda) secured by a JWT Authorizer:

- The credential provider sends the user's OIDC token in the `Authorization: Bearer` header
- API Gateway validates the JWT against the configured OIDC issuer and client ID before invoking Lambda
- User identity (email, groups) is extracted from the **validated JWT claims**, not from query parameters
- This means users cannot spoof their identity to bypass quota checks — the claims come from the IdP

The OIDC configuration for the API is automatically passed from the deployment profile during `ccwb deploy quota`.

---

## Architecture Summary

```
                                        ┌─────────────────────┐
                                        │  Identity Provider   │
                                        │ (Okta/Azure/Auth0)   │
                                        └──────────┬──────────┘
                                                   │ OIDC token
                                                   ▼
┌──────────────┐    credential_process    ┌─────────────────────┐
│  Claude Code  │◄────────────────────────│  Credential Provider │
│              │    AWS credentials        │                     │
└──────┬───────┘    (or exit code 1)      └──────┬──────────────┘
       │                                         │
       │ Direct Bedrock API calls                │ JWT in Authorization header
       │ (no gateway in this path)               ▼
       ▼                                  ┌─────────────────────┐
┌──────────────┐                          │  API Gateway         │
│   Amazon     │                          │  (JWT Authorizer)    │
│   Bedrock    │                          └──────┬──────────────┘
└──────────────┘                                 │
                                                 ▼
                                          ┌─────────────────────┐
                                          │  Quota Check Lambda  │
                                          │  - Resolve policy    │
                                          │  - Check unblock     │
                                          │  - Compare usage     │
                                          └──────┬──────────────┘
                                                 │
                              ┌───────────────────┼───────────────────┐
                              ▼                   ▼                   ▼
                       ┌─────────────┐   ┌──────────────┐   ┌──────────────┐
                       │ QuotaPolicies│   │UserQuotaMetrics│  │  Unblock     │
                       │  (DynamoDB)  │   │  (DynamoDB)   │  │  Records     │
                       └─────────────┘   └──────────────┘   └──────────────┘

Separately (every 15 min):
  EventBridge → Quota Monitor Lambda → scans UserQuotaMetrics → SNS alerts
```

---

## Key Design Decisions

- **Aggregate, not per-model.** Quotas track total tokens across all Claude models. There is no mechanism to set different limits per model.
- **Server-side only.** Even if a user tampers with their local binary to skip the quota check, enforcement happens again at credential refresh. The worst case is continued access until the current credentials expire.
- **No gateway in the Bedrock path.** Quota checks add no latency to actual model invocations. The API Gateway exists only for the quota check endpoint and distribution landing page.
- **Fail-closed by default in Lambda.** The Quota Check Lambda defaults to denying access on errors (missing email claim, DynamoDB failures). The credential provider client defaults to fail-open to avoid locking users out due to transient network issues. These are independently configurable.
- **Monthly and daily resets are calendar-based (UTC).** Monthly resets on the 1st; daily resets at midnight UTC.
