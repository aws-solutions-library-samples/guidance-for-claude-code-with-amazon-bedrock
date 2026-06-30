# Bootstrap Server

The CoWork Bootstrap Server delivers per-user configuration to Claude Desktop (CoWork) clients dynamically at sign-in. Instead of baking full configuration into static MDM profiles, administrators deploy a lightweight API endpoint that validates the user's OIDC token and returns their personalized settings — inference region, allowed models, OTEL endpoint, and session lifetime.

This enables organizations to change configuration centrally without re-deploying MDM profiles, support different config per user/group (future v2), and ensure configuration is only delivered to authenticated users with valid OIDC tokens.

## How It Works

```
┌─────────────┐     1. Sign in (OIDC)      ┌──────────────┐
│  CoWork     │ ──────────────────────────► │  OIDC IdP    │
│  (Client)   │ ◄────────────────────────── │  (Okta/Azure)│
│             │     2. Receive token        └──────────────┘
│             │
│             │     3. GET /config           ┌──────────────┐
│             │        Authorization:        │  Bootstrap   │
│             │        Bearer <token>        │  Server      │
│             │ ──────────────────────────► │  (Lambda)    │
│             │                              │              │
│             │     4. Validate JWT          │  - Verify    │
│             │        against JWKS          │    signature │
│             │                              │  - Check iss │
│             │     5. Return config JSON    │  - Check aud │
│             │ ◄────────────────────────── │  - Check exp │
└─────────────┘                              └──────────────┘
```

1. User signs into CoWork via OIDC (standard flow)
2. CoWork receives an access/ID token from the IdP
3. CoWork calls the bootstrap URL with the Bearer token
4. Lambda validates the JWT signature against the IdP's JWKS
5. Lambda returns per-user configuration JSON

## Configuration Options

The bootstrap server is configured during `ccwb init` and deployed with `ccwb deploy bootstrap`.

### Init Wizard

During `ccwb init`, after the CoWork 3P section:

```
CoWork configuration delivery:
  ❯ Static (default — MDM profile with inline config)
    Dynamic (bootstrap server — per-user config at sign-in)
```

### CloudFormation Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `OidcIssuerUrl` | OIDC issuer URL for token validation | (from profile) |
| `OidcClientId` | Client ID for audience validation | (from profile) |
| `OidcJwksEndpoint` | JWKS endpoint for signature verification | (auto-derived) |
| `DefaultInferenceRegion` | AWS region for Bedrock inference | `us-east-1` |
| `DefaultInferenceModels` | Comma-separated allowed model IDs | Sonnet |
| `OtlpEndpoint` | OpenTelemetry collector endpoint | (optional) |
| `InferenceSessionLifetimeSec` | Session lifetime before re-auth | `28800` (8h) |

### Response Format

```json
{
  "inferenceProvider": "bedrock",
  "inferenceRegion": "us-east-1",
  "inferenceModels": ["us.anthropic.claude-sonnet-4-20250514-v1:0"],
  "inferenceSessionLifetimeSec": 28800,
  "otlpEndpoint": "https://otel.example.com",
  "otlpHeaders": {
    "x-user-id": "user-sub-claim",
    "x-user-email": "user@example.com"
  },
  "expiresAt": 1719352800,
  "user": {
    "sub": "user-sub-claim",
    "email": "user@example.com"
  }
}
```

## Security Considerations

- **Token validation**: Every request must include a valid JWT Bearer token. The Lambda validates the signature against the IdP's JWKS, checks issuer (`iss`), audience (`aud`), and expiration (`exp`) claims.
- **No caching**: Responses include `Cache-Control: no-store` to prevent stale configuration.
- **HTTPS only**: API Gateway enforces HTTPS. The JWKS endpoint must also be HTTPS.
- **Short-lived config**: The `expiresAt` field (1 hour) tells clients when to re-fetch. This limits exposure if a config response is somehow captured.
- **No secrets in response**: The config response contains no credentials — only configuration directives. Authentication for Bedrock remains handled by the credential helper.

## How Clients Connect (MDM Anchor Profile)

When using dynamic configuration, deploy a minimal MDM "anchor" profile that only contains the bootstrap URL. The client fetches full configuration from the server at sign-in:

```json
{
  "coworkOAuthClientId": "your-oidc-client-id",
  "coworkOAuthIssuer": "https://your-idp.example.com/oauth2/default",
  "bootstrapUrl": "https://abc123.execute-api.us-east-1.amazonaws.com/config"
}
```

This replaces the need for a full static MDM profile with all inference settings inlined. The client authenticates, receives its token, calls the bootstrap URL, and receives its full configuration.

## Deployment

```bash
# Initialize with dynamic config mode
poetry run ccwb init
# Select "Dynamic" when prompted for CoWork configuration delivery

# Deploy the bootstrap server stack
poetry run ccwb deploy bootstrap

# Or deploy all stacks (bootstrap is included when dynamic mode is configured)
poetry run ccwb deploy
```

## Supported Identity Providers

The bootstrap server works with any OIDC-compatible IdP:

- **Okta** — JWKS at `{issuer}/v1/keys`
- **Azure AD / Entra ID** — JWKS at `login.microsoftonline.com/{tenant}/discovery/v2.0/keys`
- **Google Workspace** — JWKS at `googleapis.com/oauth2/v3/certs`
- **Amazon Cognito** — JWKS at `{user-pool-url}/.well-known/jwks.json`
- **Auth0** — JWKS at `{issuer}/.well-known/jwks.json`
- **Generic OIDC** — Any provider with a standard JWKS endpoint

> **Note**: IAM Identity Center (IDC) is not supported for bootstrap server in v1. Use static MDM profiles for IDC deployments.
