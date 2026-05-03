# Complete Keycloak Setup Guide for Amazon Bedrock Integration

This guide walks you through setting up Keycloak to work with the Claude Code authentication system for Amazon Bedrock access.

## Overview

| Component | Client Type | Purpose |
|-----------|------------|---------|
| **Client 1 — Credential Provider** | Public | OAuth2/PKCE authentication for CLI users |
| **Client 2 — Landing Page** | Confidential | ALB OIDC authentication for package distribution portal |
| **Telemetry (OTEL)** | — | Reuses Client 1 tokens via JWKS (no extra client needed) |

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Prepare Your Realm](#2-prepare-your-realm)
3. [Client 1 — Credential Provider (Public Client)](#3-client-1--credential-provider-public-client)
4. [Client 2 — Landing Page Distribution (Confidential Client)](#4-client-2--landing-page-distribution-confidential-client)
5. [Create Test Users](#5-create-test-users)
6. [TLS Thumbprint](#6-tls-thumbprint)
7. [Telemetry (OTEL Collector)](#7-telemetry-otel-collector)
8. [Summary — Values for ccwb init](#8-summary--values-for-ccwb-init)
9. [Token Lifetime Configuration](#9-token-lifetime-configuration)
10. [Post-Deployment](#10-post-deployment)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

- Keycloak server running with HTTPS enabled (e.g., `https://keycloak.example.com`)
- Admin access to the Keycloak Administration Console
- Custom domain names for landing page and telemetry endpoints (if using those features)

---

## 2. Prepare Your Realm

### Step 2.1: Create a Realm (or Use Existing)

1. Log in to the Keycloak Admin Console at `https://keycloak.example.com/admin`
2. Click the realm dropdown in the top-left corner
3. Click **Create Realm**
4. Enter a **Realm name** (e.g., `claude-code`)
5. Set **Enabled** to `ON`
6. Click **Create**

> **Tip**: You can also use an existing realm if you prefer to manage Claude Code users alongside other applications.

### Step 2.2: Verify OIDC Discovery Endpoint

Confirm the OIDC discovery endpoint is accessible:

```
https://keycloak.example.com/realms/claude-code/.well-known/openid-configuration
```

This URL should return a JSON document containing endpoints for authorization, token exchange, and JWKS. Note your **realm URL** — you'll need it later:

```
https://keycloak.example.com/realms/claude-code
```

---

## 3. Client 1 — Credential Provider (Public Client)

This client handles OAuth2/PKCE authentication for CLI users.

### Step 3.1: Create the Client

1. In the Admin Console, navigate to **Clients** → **Create client**
2. Configure:
   - **Client type**: OpenID Connect
   - **Client ID**: `claude-code-cli` (or your preferred name)
   - **Name**: `Claude Code CLI Authentication`
3. Click **Next**

### Step 3.2: Configure Capability Settings

1. Set:
   - **Client authentication**: `OFF` (this makes it a public client)
   - **Authorization**: `OFF`
   - **Standard flow**: `ON` (Authorization Code flow)
   - **Direct access grants**: `OFF`
2. Click **Next**

### Step 3.3: Configure Login Settings

1. Set:
   - **Valid redirect URIs**: `http://localhost:8400/callback`
   - **Valid post logout redirect URIs**: `http://localhost:8400/logout` (optional)
   - **Web origins**: `http://localhost:8400`
2. Click **Save**

### Step 3.4: Verify Default Scopes

1. Go to your client → **Client scopes** tab
2. Verify that these scopes are assigned as **Default**:
   - `basic`
   - `profile`
   - `email`
3. These scopes ensure the ID token includes the `email`, `sub`, and `name` claims required by the credential provider

### Step 3.5: Note the Client ID

Copy the **Client ID** (e.g., `claude-code-cli`) — you'll need it for `ccwb init`.

---

## 4. Client 2 — Landing Page Distribution (Confidential Client)

This client is only needed if you use the authenticated landing page for package distribution.

### Step 4.1: Create the Client

1. Navigate to **Clients** → **Create client**
2. Configure:
   - **Client type**: OpenID Connect
   - **Client ID**: `claude-code-landing` (or your preferred name)
   - **Name**: `Claude Code Landing Page`
3. Click **Next**

### Step 4.2: Configure Capability Settings

1. Set:
   - **Client authentication**: `ON` (confidential client)
   - **Authorization**: `OFF`
   - **Standard flow**: `ON`
   - **Direct access grants**: `OFF`
2. Click **Next**

### Step 4.3: Configure Login Settings

1. Set:
   - **Valid redirect URIs**: `https://your-landing-page-domain.example.com/oauth2/idpresponse`
   - **Web origins**: `https://your-landing-page-domain.example.com`
2. Click **Save**

> **Note**: You'll update the redirect URI with the actual ALB domain after deployment.

### Step 4.4: Get Client Secret

1. Go to your client → **Credentials** tab
2. Copy the **Client secret** — you'll need this for `ccwb init`

---

## 5. Create Test Users

### Step 5.1: Create a User

1. Navigate to **Users** → **Add user**
2. Fill in:
   - **Username**: `testuser`
   - **Email**: `testuser@example.com`
   - **Email verified**: `ON`
   - **First name**: `Test`
   - **Last name**: `User`
3. Click **Create**

### Step 5.2: Set Password

1. Go to the user → **Credentials** tab
2. Click **Set password**
3. Enter a password
4. Set **Temporary** to `OFF` (for testing convenience)
5. Click **Save**

### Step 5.3: Create Additional Users (Optional)

Repeat the process for additional test users as needed.

---

## 6. TLS Thumbprint

AWS IAM OIDC Provider requires a TLS certificate thumbprint. Since July 2023, AWS uses its own trust store and may ignore this value for validation, but some regions reject an all-zeros placeholder.

Extract the SHA-1 thumbprint of your Keycloak server's TLS certificate:

```bash
openssl s_client -connect keycloak.example.com:443 2>/dev/null \
  | openssl x509 -fingerprint -sha1 -noout \
  | sed 's/://g' | cut -d= -f2
```

This returns a 40-character hex string (e.g., `A1B2C3D4E5F6...`). Note this value for `ccwb init`.

---

## 7. Telemetry (OTEL Collector)

No additional Keycloak client is required for telemetry. The OTEL collector validates user identity by fetching the JWKS from your realm's well-known endpoint:

```
https://keycloak.example.com/realms/claude-code/protocol/openid-connect/certs
```

The OTEL helper extracts user identity from the cached JWT tokens issued by Client 1.

---

## 8. Summary — Values for `ccwb init`

When running `poetry run ccwb init`, you'll be prompted for these values:

### OIDC Configuration

| Prompt | Value | Example |
|--------|-------|---------|
| **Provider type** | `keycloak` | `keycloak` |
| **Keycloak domain** | Your Keycloak hostname | `keycloak.example.com` |
| **Keycloak realm** | Your realm name | `claude-code` |
| **Client ID** | Client 1 client ID | `claude-code-cli` |
| **TLS thumbprint** | SHA-1 thumbprint from Step 6 | `A1B2C3D4E5F6...` |

### Landing Page Distribution (if enabled)

| Prompt | Value | Example |
|--------|-------|---------|
| **Landing page client ID** | Client 2 client ID | `claude-code-landing` |
| **Landing page client secret** | Client 2 secret from Credentials tab | `abc123...` |

### Monitoring (if enabled)

| Prompt | Value |
|--------|-------|
| **OTEL authentication** | No extra configuration needed — uses Client 1 JWKS |

---

## 9. Token Lifetime Configuration

**Important**: Keycloak's default Access Token Lifespan is **1 minute**, which is too short for credential exchange with AWS. You must increase this value.

### Option A: Realm-Wide Setting (Recommended)

1. Navigate to **Realm settings** → **Tokens** tab
2. Set **Access Token Lifespan** to a longer value (see table below)
3. Click **Save**

### Option B: Per-Client Override

1. Navigate to **Clients** → your client → **Advanced** tab
2. Under **Advanced Settings**, set **Access Token Lifespan** override
3. Click **Save**

### Recommended Values

| Setting | Recommended | Notes |
|---------|-------------|-------|
| **Access Token Lifespan** | `5 minutes` – `60 minutes` | Must be long enough for STS token exchange |
| **SSO Session Idle** | `30 minutes` | How long before an idle session expires |
| **SSO Session Max** | `10 hours` | Maximum session duration |

> **Note**: The credential provider caches AWS credentials and refreshes them before expiry, so the access token only needs to be valid long enough for the initial STS exchange. A 5-minute minimum is recommended; 60 minutes provides a comfortable buffer.

---

## 10. Post-Deployment

After running `ccwb deploy`, complete these steps:

### Update Redirect URIs

If you deployed the landing page, update Client 2's redirect URI with the actual ALB domain:

1. Go to **Clients** → `claude-code-landing` → **Settings** tab
2. Update **Valid redirect URIs** to: `https://<actual-alb-domain>/oauth2/idpresponse`
3. Click **Save**

### External DNS (if not using Route 53)

If you chose "Skip (use external DNS provider)" during `ccwb init`, create CNAME records in your DNS provider:

| Record | Type | Target |
|--------|------|--------|
| `landing.example.com` | CNAME | ALB DNS name from `ccwb status` output |
| `telemetry.example.com` | CNAME | Monitoring ALB DNS name from `ccwb status` output |

### Assign Users

Grant users access to Claude Code by ensuring they have accounts in your Keycloak realm with verified email addresses. No application assignment step is required — any user in the realm can authenticate with the public client.

To restrict access, configure Keycloak's **Authorization** features or use **Client Policies** to limit which users can obtain tokens.

---

## 11. Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `invalid_client` error | Client authentication mismatch | Verify Client 1 has **Client authentication** set to `OFF` (public client) |
| `invalid_redirect_uri` | Redirect URI mismatch | Ensure redirect URI is exactly `http://localhost:8400/callback` (no trailing slash) |
| Token exchange fails immediately | Access token too short | Increase **Access Token Lifespan** to at least 5 minutes (see [Step 9](#9-token-lifetime-configuration)) |
| `aud` claim mismatch | Wrong audience in token | Verify the Client ID in `ccwb init` matches the Keycloak client ID exactly |
| JWKS fetch fails | Realm URL incorrect | Verify `https://<domain>/realms/<realm>/.well-known/openid-configuration` is accessible |
| TLS thumbprint rejected | Invalid thumbprint format | Re-run the openssl command from [Step 6](#6-tls-thumbprint); must be 40 hex characters |
| Landing page 401/403 | Client secret wrong or expired | Regenerate the client secret in Client 2's **Credentials** tab and update `ccwb init` |
| User can't sign in | Account not active or email not verified | Check user status in **Users** and ensure **Email verified** is `ON` |

---

## Next Steps

Once you've completed this Keycloak setup:

1. Run the setup wizard: `poetry run ccwb init`
2. Deploy infrastructure: `poetry run ccwb deploy`
3. Create a distribution package: `poetry run ccwb package`
4. Test the deployment: `poetry run ccwb test --api`
5. Distribute the `dist/` folder to your users

---

## Security Best Practices

1. **TLS Required**: Always run Keycloak behind HTTPS. The OIDC discovery and JWKS endpoints must be served over TLS.
2. **Token Lifetimes**: Keep access tokens short (5–60 minutes). The credential provider handles refresh automatically.
3. **User Management**: Use Keycloak groups and roles to manage access at scale. Enable MFA via Keycloak's authentication flows.
4. **Realm Isolation**: Consider using a dedicated realm for Claude Code to isolate user populations and token policies.
5. **Client Secrets**: Rotate the landing page client secret periodically. Store it securely — it's needed only during `ccwb init`.
