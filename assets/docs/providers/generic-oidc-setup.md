# Generic OIDC Setup Guide (PingFederate, Keycloak, ForgeRock, etc.)

This guide covers setting up a generic OIDC identity provider for use with Amazon Bedrock. Use this path when your IdP is **not** Okta, Auth0, Microsoft Entra ID (Azure AD), or AWS Cognito User Pool — for example PingFederate, Keycloak, ForgeRock, or a custom OIDC-compliant deployment.

> **Why this guide exists:** Earlier versions of this solution treated the "Okta (or generic OIDC)" choice as Okta-specific. Selecting it for a non-Okta IdP failed in several places (CFN domain regex, hardcoded Okta thumbprint, Okta-only OAuth endpoint paths). The dedicated `Generic OIDC` choice in `ccwb init` fixes this.

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create OIDC Application in Your IdP](#2-create-oidc-application-in-your-idp)
3. [Collect Required Information](#3-collect-required-information)
4. [Run ccwb init](#4-run-ccwb-init)
5. [Worked Example: PingFederate](#5-worked-example-pingfederate)
6. [Worked Example: Keycloak](#6-worked-example-keycloak)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Prerequisites

Your IdP must:

- Implement **OIDC 1.0** with the **Authorization Code + PKCE** flow (the credential helper does not support implicit, ROPC, or device flows).
- Issue tokens whose `iss` claim **exactly** matches the issuer URL you configure in `ccwb init`. AWS IAM validates this on every `AssumeRoleWithWebIdentity` call.
- Allow `http://localhost:8400/callback` as a redirect URI for your application registration.
- Expose a public JWKS endpoint (the URL is required at deploy time and at every token validation).

If your IdP also publishes `/.well-known/openid-configuration`, `ccwb init` will auto-discover the endpoint URLs for you. Most modern IdPs do.

---

## 2. Create OIDC Application in Your IdP

The exact UI varies by product, but every IdP needs you to configure these properties:

| Setting | Value | Notes |
|---|---|---|
| Application / client type | **Public client** (or "native", "SPA", "desktop") | Confidential client requires a client secret — only Azure AD currently supports that path here. |
| Grant types | **Authorization Code** with **PKCE** | Refresh tokens optional but recommended. |
| Redirect URI | `http://localhost:8400/callback` | Exact match. The credential helper auto-falls-back to a random port if 8400 is taken — if your IdP requires that to be allowlisted too, see [Troubleshooting](#7-troubleshooting). |
| Scopes | `openid`, `profile`, `email` | `groups` if you plan to use group-based quotas. |
| ID token signing | **RS256** or stronger | HS256 is not supported by the credential helper. |

Do **not** set a client secret. The credential helper uses PKCE instead.

---

## 3. Collect Required Information

Before running `ccwb init`, gather these five values:

| Value | Description | Example |
|---|---|---|
| **Issuer URL** | The exact value of the `iss` claim in tokens issued by your IdP. Must start with `https://`. | `https://auth.example.com` |
| **Client ID** | The OIDC application client ID from the IdP. | `bedrock-cli-prod` |
| **Authorization endpoint** | Full URL where the user is redirected to log in. | `https://auth.example.com/as/authorization.oauth2` |
| **Token endpoint** | Full URL the credential helper POSTs to for code exchange. | `https://auth.example.com/as/token.oauth2` |
| **JWKS URI** | Public JWKS endpoint that AWS IAM uses to validate ID tokens. | `https://auth.example.com/pf/JWKS` |

You also need the **SHA-1 thumbprint** of the JWKS endpoint's TLS leaf certificate. `ccwb init` computes this automatically via TLS handshake — the manual command is in the [Troubleshooting](#7-troubleshooting) section if auto-computation fails.

> **Tip:** Most of these come straight from `{issuer}/.well-known/openid-configuration`. `ccwb init` queries that automatically and pre-fills the prompts.

---

## 4. Run ccwb init

```bash
cd source
poetry install
poetry run ccwb init
```

When the wizard asks "Select your identity provider type", choose **Generic OIDC (PingFederate, Keycloak, ForgeRock, etc.)**. The wizard will:

1. Prompt for the issuer URL.
2. Query `{issuer}/.well-known/openid-configuration`. If discovery succeeds, the next three prompts (authorization endpoint, token endpoint, JWKS URI) are pre-filled — confirm or override.
3. Open a TLS connection to your JWKS endpoint to compute the leaf-cert SHA-1 thumbprint. The next prompt is pre-filled — confirm or override.
4. Continue with federation type, region, model selection, etc.

The resulting profile is saved to `~/.ccwb/profiles/<name>.json` with these new fields:

```json
{
  "provider_type": "generic",
  "oidc_issuer_url": "https://auth.example.com",
  "oidc_authorization_endpoint": "https://auth.example.com/as/authorization.oauth2",
  "oidc_token_endpoint": "https://auth.example.com/as/token.oauth2",
  "oidc_jwks_uri": "https://auth.example.com/pf/JWKS",
  "oidc_thumbprint": "9e99a48a9960b14926bb7f3b02e22da2b0ab7280"
}
```

Then deploy:

```bash
poetry run ccwb deploy auth
```

This applies `deployment/infrastructure/bedrock-auth-generic.yaml`, which provisions the IAM OIDC Provider with your issuer URL and thumbprint, plus the federated role and Bedrock policy.

---

## 5. Worked Example: PingFederate

PingFederate (self-hosted or PingOne) typically uses these endpoint paths:

| Field | Value |
|---|---|
| Issuer URL | `https://<your-pingfederate-host>` |
| Authorization endpoint | `https://<host>/as/authorization.oauth2` |
| Token endpoint | `https://<host>/as/token.oauth2` |
| JWKS URI | `https://<host>/pf/JWKS` |

**In the PingFederate admin console:**

1. **Applications → OAuth → Clients** → **Add Client**.
2. Set **Client ID** (you'll enter this in `ccwb init`).
3. **Client Authentication** → **None** (we use PKCE).
4. **Allowed Grant Types** → check **Authorization Code**. Optional: **Refresh Token**.
5. **Redirect URIs** → `http://localhost:8400/callback`.
6. **Require Proof Key for Code Exchange (PKCE)** → check.
7. **Allowed Scopes** → `openid`, `profile`, `email`.
8. Save, then complete `ccwb init` using the **Generic OIDC** option. PingFederate publishes `/.well-known/openid-configuration` by default, so endpoint discovery should succeed.

---

## 6. Worked Example: Keycloak

Keycloak's URL layout is realm-scoped:

| Field | Value |
|---|---|
| Issuer URL | `https://<keycloak-host>/realms/<realm-name>` |
| Authorization endpoint | `https://<host>/realms/<realm>/protocol/openid-connect/auth` |
| Token endpoint | `https://<host>/realms/<realm>/protocol/openid-connect/token` |
| JWKS URI | `https://<host>/realms/<realm>/protocol/openid-connect/certs` |

**In the Keycloak admin console:**

1. Select your **realm**.
2. **Clients** → **Create client**.
3. **Client type** → `OpenID Connect`. **Client ID** → e.g. `bedrock-cli`.
4. Click **Next**.
5. **Client authentication** → **Off** (public client + PKCE).
6. **Standard flow** → on. **Direct access grants** → off.
7. Click **Next**.
8. **Valid redirect URIs** → `http://localhost:8400/callback`.
9. Save the client. Open it, go to the **Advanced** tab.
10. **Proof Key for Code Exchange Code Challenge Method** → `S256`.
11. Save.

`ccwb init` discovery will work against the realm-scoped issuer URL.

---

## 7. Troubleshooting

### `Discovery failed: HTTP 404 from .../openid-configuration`

Your IdP doesn't publish a discovery document. The wizard falls through to manual entry — populate each prompt by hand using your IdP's documentation.

### `TLS handshake to <host>:443 failed`

Auto-thumbprint computation hit a network or TLS error. Compute the SHA-1 manually:

```bash
echo | openssl s_client -servername <jwks-host> -connect <jwks-host>:443 2>/dev/null \
  | openssl x509 -fingerprint -sha1 -noout
```

Strip the colons and lowercase the result before pasting into `ccwb init`.

### `Token is not from a supported provider` from STS

The `iss` claim in your ID token does not exactly match the issuer URL configured on the IAM OIDC Provider. Common causes:

- Trailing slash mismatch (`https://auth.example.com/` vs `https://auth.example.com`). AWS treats these as different.
- Keycloak realm name mismatch (typo, wrong realm).
- IdP returns the issuer with a different host than the one you registered (e.g. internal vs external hostname).

Re-run `ccwb init` and pin the issuer URL to whatever your IdP literally puts in the `iss` claim. You can decode a sample token at [jwt.io](https://jwt.io) to confirm.

### `Authentication timeout - no authorization code received`

The IdP didn't redirect back to `http://localhost:8400/callback`. Check the IdP application's allowed redirect URIs. If your network blocks `localhost:8400` specifically, set the `REDIRECT_PORT` environment variable to a different port and update the IdP application accordingly — the credential helper will use that port instead.

### `Invalid nonce in ID token`

The IdP did not echo the `nonce` parameter back in the ID token. This is required by OIDC and most modern IdPs do it correctly — if you hit this, check whether your IdP needs a configuration toggle to include `nonce`.

### Where do I find the JWKS thumbprint manually?

```bash
HOST=auth.example.com
echo | openssl s_client -servername "$HOST" -connect "$HOST:443" 2>/dev/null \
  | openssl x509 -fingerprint -sha1 -noout \
  | sed 's/.*=//;s/://g' \
  | tr 'A-Z' 'a-z'
```

### My IdP rotates the JWKS cert. What do I do?

The IAM OIDC Provider accepts multiple thumbprints. For now, the wizard only collects one — to add a second, edit `~/.ccwb/profiles/<name>.json` and set `oidc_thumbprint` to a comma-separated list, then redeploy with `poetry run ccwb deploy auth`.

---

## Cost Attribution (Optional)

Per-user Bedrock costs are tracked automatically via the session tag — no IdP changes needed. For additional attribution (department, cost center, etc.), inject those values as custom claims in the ID token and they will flow through to CloudTrail via Cognito Identity Pool principal tags. See the [Cost Attribution](../COST_ATTRIBUTION.md) guide.

---

## Next Steps

After `ccwb init` succeeds:

```bash
poetry run ccwb deploy        # deploy all configured stacks
poetry run ccwb test --api    # smoke-test authentication + Bedrock invoke
poetry run ccwb package       # build distribution for end users
```
