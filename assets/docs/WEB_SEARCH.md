# Web Search for Claude Cowork (Amazon Bedrock AgentCore)

This guide covers the optional web search capability for **Claude Cowork** (Claude Desktop in third‑party platform mode) on Amazon Bedrock. It deploys an **Amazon Bedrock AgentCore Gateway** with the fully managed **Web Search connector** and exposes it to Cowork as a managed MCP server.

> **Status:** This page documents the standalone CloudFormation template (`deployment/infrastructure/bedrock-agentcore-gateway.yaml`). `ccwb` CLI integration (init wizard + automatic MDM wiring) ships in follow‑up PRs; until then, wire the gateway to Cowork manually as described below.

## What it does

The [Web Search tool on Amazon Bedrock AgentCore](https://aws.amazon.com/blogs/aws/announcing-web-search-on-amazon-bedrock-agentcore-ground-your-ai-agents-in-current-accurate-web-knowledge/) is a managed, MCP‑compliant connector backed by Amazon's own web index. It returns titles, URLs, snippets, and publication dates so the model can ground answers in current information. There is no third‑party search API to provision and no outbound credentials to manage — queries stay within AWS.

The template provisions:

- An **AgentCore Gateway** (MCP protocol) whose inbound authorization (`CUSTOM_JWT`) reuses your existing OIDC identity provider — the same one the rest of this solution already uses.
- A **Gateway target** configured with the managed `web-search` connector (optional domain denylist).
- A least‑privilege **gateway execution IAM role** (`GetGateway`, `GetConfigurationBundleVersion`, `InvokeWebSearch`).

## Prerequisites

- This solution already deployed with an OIDC identity provider (the Web Search gateway reuses it for inbound auth).
- Deployment into a region where the Web Search connector is available — **`us-east-1` only** at time of writing.

## Deployment

```bash
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name <your-stack-name> \
  --template-file deployment/infrastructure/bedrock-agentcore-gateway.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      WebSearchRegion=us-east-1 \
      JwtValidationMode=client_id \
      JwtDiscoveryUrl=https://cognito-idp.<idp-region>.amazonaws.com/<user-pool-id>/.well-known/openid-configuration \
      JwtAllowedClients=<your-app-client-id>
```

### Parameters

| Parameter | Description |
|-----------|-------------|
| `WebSearchRegion` | Region to deploy into. Constrained to where the connector is GA (`us-east-1`). |
| `JwtValidationMode` | `client_id` (Cognito — validates against `AllowedClients`) or `audience` (Entra ID / Okta / Auth0 / generic OIDC — validates against the token `aud` via `AllowedAudience`). |
| `JwtDiscoveryUrl` | Your IdP OIDC discovery URL (ends with `/.well-known/openid-configuration`). |
| `JwtAllowedClients` | Allowed client IDs (use with `JwtValidationMode=client_id`). |
| `JwtAllowedAudience` | Allowed `aud` values (use with `JwtValidationMode=audience`). For Entra ID this is the API Application ID URI, e.g. `api://<app-id>`. |
| `WebSearchDomainDenylist` | Optional. Comma‑separated domains to exclude from results. |

The stack output **`GatewayMcpEndpoint`** is the MCP endpoint URL to give to Claude Cowork.

## Data residency

> ⚠️ Web search queries (and fragments of user prompts) are processed by the managed connector in **`WebSearchRegion`** (`us-east-1` today), regardless of where the user's IDE session runs or where Bedrock inference happens. Organizations with data residency or sovereignty obligations (e.g. GDPR) should evaluate whether this is acceptable before enabling web search.

## Wire it to Claude Cowork (manual, until CLI support lands)

Add a `managedMcpServers` entry to your Cowork MDM configuration pointing at the gateway endpoint. Cowork authenticates with an OAuth authorization‑code flow against the **same IdP**, reusing your existing client ID and the `localhost` callback port (default `8400`) — no secret is stored in the config:

```json
{
  "managedMcpServers": "[{\"name\": \"agentcore-websearch\", \"transport\": \"http\", \"url\": \"<GatewayMcpEndpoint>\", \"oauth\": {\"clientId\": \"<your-app-client-id>\", \"authorizationServer\": [\"<oidc-issuer>\"], \"scope\": \"openid email profile\", \"callbackHost\": \"localhost\", \"callbackPort\": 8400}}]"
}
```

- `<GatewayMcpEndpoint>` — the stack output (already includes the `/mcp` path).
- `<oidc-issuer>` — for Cognito `https://cognito-idp.<region>.amazonaws.com/<user-pool-id>`; for Entra ID your Entra issuer.
- The IdP app client must already allow the `http://localhost:8400/...` redirect URI (this solution already requires it for Claude Code).

See [COWORK_3P.md](COWORK_3P.md) for the full MDM configuration reference and the custom‑MDM‑key mechanism.

## Cost

Web Search on Amazon Bedrock AgentCore is usage‑based: **$7 per 1,000 search queries** at time of writing (the gateway itself has no fixed hourly charge). See the [Amazon Bedrock AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) page for current pricing. New AWS customers may receive Free Tier credits.

## References

- [Announcing Web Search on Amazon Bedrock AgentCore](https://aws.amazon.com/blogs/aws/announcing-web-search-on-amazon-bedrock-agentcore-ground-your-ai-agents-in-current-accurate-web-knowledge/)
- [AgentCore Gateway documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [CoWork 3P Guide](COWORK_3P.md)
