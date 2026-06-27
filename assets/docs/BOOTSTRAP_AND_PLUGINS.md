# Bootstrap Server & Organization Plugins

Deploy a bootstrap server to deliver per-user configuration and organization plugins to Claude Desktop (CoWork) at sign-in. Same plugins work with Claude Code CLI via the marketplace system.

## Quick Start

```bash
ccwb init                      # Select "Dynamic (device-code)" for CoWork delivery
ccwb deploy --stack bootstrap  # Deploy the bootstrap server
# Add the printed callback URL to your IdP app's redirect URIs
# Set bootstrapUrl in your MDM profile
```

Users open Claude Desktop → see device code → log in → config + plugins delivered automatically.

## How It Works

1. **MDM profile** contains only `bootstrapUrl` (no `bootstrapOidc` → activates device-code mode)
2. Desktop shows a user code and opens the verification page
3. User logs in via their corporate IdP (Okta/Azure/Google)
4. Desktop receives config (region, models, session lifetime) + `organizationPluginsUrl`
5. Desktop fetches plugin registry and git-clones each org plugin

## Organization Plugins

### Create a plugins repo

```
your-org/claude-org-plugins/
├── security-policy/
│   ├── .claude-plugin/plugin.json
│   ├── skills/code-review/SKILL.md
│   └── hooks/pre-tool-use.md
├── internal-tools/
│   ├── .claude-plugin/plugin.json
│   └── commands/deploy.md
└── README.md
```

Each plugin needs `.claude-plugin/plugin.json`:

```json
{
  "name": "security-policy",
  "version": "1.0.0",
  "description": "Org-wide code review and security enforcement",
  "installationPreference": "required"
}
```

### Register and sync

```bash
ccwb plugins add --name security-policy \
  --repo https://github.com/your-org/claude-org-plugins.git \
  --path security-policy
ccwb plugins sync
```

### Both surfaces, one repo

| Surface | How plugins arrive | Admin action |
|---------|-------------------|--------------|
| **Claude Desktop** | Auto-installed at sign-in via bootstrap server | `ccwb plugins sync` |
| **Claude Code CLI** | `/plugin marketplace add your-org/claude-org-plugins` | Share repo URL with devs |

Same plugin format, same git repo — different delivery mechanisms.

## Auth Flow Configuration

The bootstrap server reuses your existing IdP app registration. One extra redirect URI is needed:

| IdP | Callback URL config |
|-----|-------------------|
| **Cognito** | Automatic (CFN adds to UserPoolClient) |
| **Okta** | Add callback URL in Okta admin → Applications → Sign-in redirect URIs |
| **Azure/Entra** | Add in Azure Portal → App registrations → Authentication → Redirect URIs |
| **Google** | Add in Google Cloud Console → Credentials → Authorized redirect URIs |
| **IDC** | N/A (uses AWS SSO-OIDC natively) |

The callback URL is printed after `ccwb deploy --stack bootstrap`.

## Infrastructure

| Resource | Purpose | Cost |
|----------|---------|------|
| API Gateway REST API v1 | All routes | Free tier |
| Lambda × 2 | Handler + authorizer | Free tier |
| DynamoDB | Device-code grants (TTL 5min) | $0 at rest |
| WAF (optional) | IP allowlist | $5/mo when enabled |

## Security

- JWT signature verification on all data routes (JWKS)
- Handshake routes are tokenless (RFC 8628 requirement) but expose no data
- WAF IP allowlist available for enterprise hardening
- Client secret stored in SecretsManager (never in env vars)
- `Cache-Control: no-store` on all responses
- DynamoDB TTL auto-expires grants (5 minutes)

## Example Plugin

See `deployment/examples/org-plugins/example-policy/` for a ready-to-use template.
