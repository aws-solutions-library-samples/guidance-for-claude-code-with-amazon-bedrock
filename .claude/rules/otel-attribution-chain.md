# OTEL Attribution Chain

User identity flows through multiple layers. A break in any layer
causes anonymous telemetry — invisible to the user but breaks cost
attribution and quota enforcement.

## The chain

```
OIDC token (email, sub, groups)
  → otel-helper: ExtractUserInfo → FormatHeaders
    → cache file (per-profile JSON)
      → OTEL collector reads headers → CloudWatch dimensions
```

## Rules

- Never emit empty headers when a cached valid token exists (check cache FIRST)
- Empty headers TTL must be short (≤300s) to limit the attribution gap
- `x-user-email` must ALWAYS be present (fallback: `"unknown@example.com"`)
- `FormatHeaders` must exclude empty strings (don't send `x-team-id=""`)
- Sidecar mode: reads local cache file directly
- Proxy mode: ALB forwards headers from JWT validation
- IDC mode: no JWT → no OTEL attribution (document clearly, don't crash)

## Header contract (stable — never rename these)

| Header | Source claim | Fallback |
|--------|-------------|----------|
| `x-user-email` | `email` | `"unknown@example.com"` |
| `x-user-id` | `sub` | (omit) |
| `x-user-name` | `preferred_username` → email prefix | (omit) |
| `x-department` | `department` | (omit) |
| `x-team-id` | `team` / `groups` | (omit) |
| `x-cost-center` | `cost_center` | (omit) |
| `x-project` | custom tag key from config | (omit) |

## Testing

- Token with all claims → verify all headers present
- Token with only `sub` → verify email fallback + `x-user-id` present
- Expired token → verify cache served until TTL
- Empty cache + no token → verify empty headers emitted (not crash)
- Sidecar: verify local cache file read correctly
- Proxy: verify ALB-forwarded headers match expected format

*Issues: #361, #365, #441, #446*

## Metric Sources

The OTEL collector ingests metrics from two sources:
1. **Claude Code client** — telemetry emitted by the IDE extension/CLI (e.g., `claude_code.cost.usage`, `claude_code.token.usage`). Defined by Anthropic, may change between versions.
2. **Server-side Lambdas** — cost estimator, quota monitor (e.g., `claude_code.cost.estimated`).

Do not assume a metric is unused because our server code doesn't emit it. When modifying dashboard widgets, treat existing metric references as potentially valid client-emitted data. Use distinct names for server-side metrics to avoid collisions.
