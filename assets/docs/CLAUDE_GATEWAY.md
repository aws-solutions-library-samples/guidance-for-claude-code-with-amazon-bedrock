# Claude Apps Gateway

The Claude Apps Gateway is a self-hosted control plane that sits between your developers' Claude Code CLI and Amazon Bedrock. Developers sign in with corporate SSO instead of managing cloud credentials — the Gateway holds the upstream Bedrock credential and handles authentication, policy enforcement, spend caps, and telemetry.

## When to use the Gateway

| Scenario | Use Gateway? | Alternative |
|----------|-------------|-------------|
| Many Claude Code CLI developers, need SSO | ✅ Yes | credential-process per machine |
| Per-user spend limits needed | ✅ Yes | CCWB quota stack (token-based) |
| Centralized managed settings | ✅ Yes | MDM-deployed managed-settings.json |
| Claude Desktop (Cowork) users | ❌ No | credential-helper + MDM/bootstrap |
| Small team, simple setup | Maybe | credential-process is simpler |

## What the Gateway provides

- **SSO login** — developers authenticate via your IdP (Okta, Azure, Google). No API keys on laptops.
- **Managed settings** — model allowlists, permissions, and policies delivered at sign-in.
- **Spend caps** — daily, weekly, monthly limits per user, group, or org (USD-based).
- **OTLP telemetry** — per-user metrics exported to your observability stack.
- **Upstream routing** — routes to Bedrock with failover support. Clients don't know or care about the upstream.

## Architecture

```
Developer laptop                    Your AWS account
─────────────────                   ────────────────
Claude Code CLI  ──── HTTPS ────►  ALB
                                    │
                                    ▼
                                   ECS Fargate
                                   (claude gateway)  ────►  Amazon Bedrock
                                    │
                                    ▼
                                   RDS PostgreSQL
                                   (sessions, policy)
```

The Gateway is the `claude` binary running in server mode (`claude gateway --port 8080`). Same executable your developers already have.

## Deploying

```bash
# Requires networking stack (VPC + subnets) + OIDC client secret in SecretsManager
ccwb deploy gateway
```

After deploy, you'll see:
```
✓ Claude Apps Gateway deployed!
Gateway URL: http://<alb-dns-name>

To connect Claude Code CLI, set in managed-settings.json:
  {"forceLoginMethod": "gateway", "forceLoginGatewayUrl": "http://<alb-dns-name>"}
```

## Connecting developers

Add the Gateway URL to `managed-settings.json` (deployed via MDM, `ccwb package`, or manually):

```json
{
  "forceLoginMethod": "gateway",
  "forceLoginGatewayUrl": "https://gateway.yourcompany.com"
}
```

When a developer runs `claude`, the CLI:
1. Detects `forceLoginGatewayUrl` in settings
2. Redirects to your IdP for SSO login
3. Receives a short-lived session token from the Gateway
4. All inference routes through the Gateway to Bedrock

No Bedrock credentials on developer machines. Offboard a developer by removing them from your IdP.

## Relationship to other CCWB components

| Component | With Gateway | Without Gateway |
|-----------|-------------|-----------------|
| **credential-process** | Not needed for CLI (Gateway handles auth) | Required per machine |
| **Monitoring (central)** | Gateway exports OTLP directly | otel-helper + collector |
| **Monitoring (sidecar)** | Gateway replaces sidecar for CLI | Local otelcol per machine |
| **Quota** | Gateway has native spend caps (USD) | DynamoDB + Lambda (token-based) |
| **Claude Desktop** | Still needs credential-helper (Gateway is CLI-only) | Same |
| **Distribution/packaging** | Minimal package (just managed-settings.json) | Full package with binaries |

## Tearing down

```bash
ccwb destroy gateway
```

Removes the ECS service, RDS instance, ALB, and all associated resources. Does not affect other CCWB stacks.

## References

- [Claude Apps Gateway docs](https://code.claude.com/docs/en/claude-apps-gateway)
- [Gateway configuration reference](https://code.claude.com/docs/en/claude-apps-gateway-config)
- [Gateway deployment guide](https://code.claude.com/docs/en/claude-apps-gateway-deploy)
- [Announcement blog](https://claude.com/blog/introducing-the-claude-apps-gateway)
