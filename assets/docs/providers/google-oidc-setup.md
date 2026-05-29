# Google OIDC Setup Guide

This guide covers setting up Google as the identity provider for Claude Code with Amazon Bedrock. Use this when your organization uses **Google Workspace** and you want users to authenticate with their existing Google accounts.

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create OAuth Application in Google Cloud Console](#2-create-oauth-application-in-google-cloud-console)
3. [Collect Required Information](#3-collect-required-information)
4. [Run ccwb init](#4-run-ccwb-init)
5. [Important Notes](#5-important-notes)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Prerequisites

- A **Google Cloud project** with the OAuth consent screen configured
- Your Google Workspace domain (e.g., `example.com`) — or personal Google accounts if testing
- AWS account with permissions to create IAM OIDC providers and roles

---

## 2. Create OAuth Application in Google Cloud Console

1. Go to [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **Create Credentials → OAuth client ID**
3. Select application type: **Desktop app** (or "Web application" if you prefer)
4. Configure:

| Setting | Value |
|---------|-------|
| Application type | Desktop app |
| Name | Claude Code with Bedrock |
| Authorized redirect URIs | `http://localhost:8400/callback` |

5. Click **Create** and note the **Client ID** and **Client Secret**

> **Note:** Unlike other providers in this solution, Google OAuth requires a `client_secret` for the authorization code exchange even with PKCE. The secret is included in the packaged `config.json` distributed to end users. This is standard for Google's "installed application" OAuth flow — the secret is not considered confidential in this context (see [Google's documentation](https://developers.google.com/identity/protocols/oauth2/native-app)).

---

## 3. Collect Required Information

| Value | Where to find it | Example |
|-------|-------------------|---------|
| Provider domain | Always `accounts.google.com` | `accounts.google.com` |
| Client ID | Google Cloud Console → Credentials | `123456789-abc.apps.googleusercontent.com` |
| Client Secret | Google Cloud Console → Credentials | `GOCSPX-...` |

---

## 4. Run ccwb init

```bash
poetry run ccwb init
```

The wizard will:
1. Ask for your provider domain — enter `accounts.google.com`
2. Auto-detect the provider type as **Google**
3. Ask for your **Client ID**
4. Ask for your **Client Secret** (stored in the profile and included in packaged config)
5. Continue with region, model, and monitoring configuration

---

## 5. Important Notes

### Token Endpoint

Google uses a different domain for token exchange (`oauth2.googleapis.com`) than for authorization (`accounts.google.com`). The credential helper handles this automatically.

### IAM OIDC Provider

The CloudFormation template (`bedrock-auth-google.yaml`) creates an IAM OIDC provider with:
- Issuer URL: `https://accounts.google.com`
- Audience: Your Google Client ID
- Thumbprint: Automatically computed from Google's JWKS endpoint

### Session Duration

With Direct IAM federation (recommended), sessions last up to **12 hours**. The credential helper caches credentials and refreshes them silently using the cached ID token when possible.

### Restricting Access to Your Domain

The IAM role trust policy restricts access by **audience** (your Client ID). Since only users in your Google Cloud project can obtain tokens with your Client ID, access is inherently scoped to authorized users. For additional restrictions, configure the OAuth consent screen to "Internal" (Google Workspace only).

---

## 6. Troubleshooting

### "Token is not from a supported provider"

- Verify the IAM OIDC provider's issuer URL is exactly `https://accounts.google.com` (no trailing slash)
- Confirm the Client ID in your IAM OIDC provider matches the one in `config.json`

### "invalid_client" during token exchange

- Ensure the Client Secret is correctly included in `config.json`
- Verify the OAuth application in Google Cloud Console has the redirect URI `http://localhost:8400/callback`

### Browser doesn't open / callback timeout

- Check that port 8400 is not in use by another process
- If behind a corporate proxy, ensure `localhost` traffic is not intercepted
