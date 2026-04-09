# Complete Microsoft Entra ID Setup Guide for Amazon Bedrock Integration

This guide walks you through setting up Microsoft Entra ID from scratch to work with the AWS Cognito Identity Pool for Bedrock access.

## Table of Contents

1. [Create Azure Account](#1-create-azure-account)
2. [Access Azure Portal](#2-access-azure-portal)
3. [Create App Registration](#3-create-app-registration)
4. [Configure Authentication](#4-configure-authentication)
5. [Confidential Client Setup (Enterprise)](#5-confidential-client-setup-enterprise)
6. [Create Test Users](#6-create-test-users)
7. [Assign Users to Application](#7-assign-users-to-application)
8. [Collect Required Information](#8-collect-required-information)
9. [Test the Setup](#9-test-the-setup)

---

## 1. Create Azure Account

If you don't have an Azure account:

1. Go to https://azure.microsoft.com/free/
2. Click **Start free**
3. Sign in with a Microsoft account or create one
4. Complete the registration (requires credit card for verification)
5. You'll get $200 in credits and free tier access

> **Note**: Save your tenant ID - you'll need it for configuration!

---

## 2. Access Azure Portal

1. Go to https://portal.azure.com
2. Sign in with your Azure account
3. Search for **Microsoft Entra ID** in the top search bar
4. Click to access the admin center

---

## 3. Create App Registration

### Step 3.1: Start App Registration

1. In Microsoft Entra ID, navigate to **Applications** → **App registrations**
2. Click **+ New registration**

### Step 3.2: Configure Application

Fill in the following:

- **Name**: `Amazon Bedrock CLI Access`
- **Supported account types**: Select based on your needs
  - For enterprise: **Accounts in this organizational directory only**
  - For broader access: **Accounts in any organizational directory**
- **Redirect URI**: Leave blank (we'll add it next)

Click **Register**

### Step 3.3: Note Your IDs

After registration, save these values:

- **Application (client) ID**: `12345678-1234-1234-1234-123456789012`
- **Directory (tenant) ID**: `87654321-4321-4321-4321-210987654321`

---

## 4. Configure Authentication

### Step 4.1: Add Platform

The platform type you select here controls whether Azure AD enforces confidential client authentication. **Choose based on your intended auth mode:**

#### Public client (personal / dev tenant)

1. In your app registration, click **Authentication**
2. Click **+ Add a platform**
3. Select **Mobile and desktop applications**
4. Check **Add a custom redirect URI** and enter exactly:
   ```
   http://localhost:8400/callback
   ```
5. Click **Configure**

#### Confidential client (enterprise — secret or certificate)

1. In your app registration, click **Authentication**
2. Click **+ Add a platform**
3. Select **Web**
4. Under **Redirect URIs**, enter exactly:
   ```
   http://localhost:8400/callback
   ```
5. Click **Configure**

> **Important**: Using **Mobile and desktop applications** with a confidential client mode will cause Azure AD to silently skip client credential enforcement — the flow will appear to succeed even without a valid secret or certificate. Always use **Web** for confidential client setups.

### Step 4.2: Public Client vs. Confidential Client

In **Authentication** → **Advanced settings** you will find the **Allow public client flows** toggle.

| Your situation | Setting | Next step |
|---|---|---|
| Personal or dev tenant, no restrictions | **Yes** (enabled) | Continue to [Section 6](#6-create-test-users) |
| Enterprise tenant with security policy that disables public clients | **No** (leave disabled) | Follow [Section 5](#5-confidential-client-setup-enterprise) |

> **Enterprise note**: Many organisations enforce `Allow public client flows = No` as a security baseline. If yours does, do not change this setting — configure a confidential client instead (Section 5).

### Step 4.3: Verify API Permissions

The default `User.Read` permission is sufficient. No changes needed.

---

## 5. Confidential Client Setup (Enterprise)

Skip this section if you enabled public client flows in Step 4.2.

Enterprise Entra ID tenants often prohibit public client flows. The credential provider supports two confidential client modes:

| Mode | When to use |
|---|---|
| **Client secret** | Quick setup, lower security — suitable for dev/test |
| **Certificate (recommended)** | No long-lived secret on disk, preferred for production |

---

### Option A: Client Secret

1. In your app registration, go to **Certificates & secrets** → **Client secrets**
2. Click **+ New client secret**
3. Set a description (e.g. `ccwb-credential-provider`) and an expiry
4. Click **Add** and **copy the secret value immediately** — it is not shown again

When `ccwb init` asks for the Azure authentication mode, select **Confidential client — client secret** and paste the value. The secret is stored securely in the **OS secure storage** (keyring) on the admin machine.

#### Distributing to end users

The client secret is a **shared app secret** — every user of the app uses the same value. After installing the dist package, each user must run the following command once to store it on their machine:

```bash
# macOS / Linux
~/claude-code-with-bedrock/credential-process --set-client-secret --profile ClaudeCode

# Windows
%USERPROFILE%\claude-code-with-bedrock\credential-process.exe --set-client-secret --profile ClaudeCode
```

The user is prompted to enter the secret interactively. For automated or MDM-based deployments, set the `CCWB_CLIENT_SECRET` environment variable before running the command — this avoids the secret appearing in shell history or process listings:

```bash
CCWB_CLIENT_SECRET=<your-client-secret> ~/claude-code-with-bedrock/credential-process --set-client-secret --profile ClaudeCode
```

#### Rotating the secret

When you rotate the secret in Entra ID, re-run `ccwb init` on the admin machine and repeat the `--set-client-secret` command on each user machine (or push it via MDM).

To clear a stored secret from a machine:

```bash
~/claude-code-with-bedrock/credential-process --set-client-secret --profile ClaudeCode
# press Enter without typing a value
```

---

### Option B: Certificate (Recommended)

#### Step 5.1: Generate a self-signed certificate

On any machine with OpenSSL:

```bash
openssl req -x509 -newkey rsa:2048 \
  -keyout key.pem -out cert.pem \
  -days 365 -nodes \
  -subj "/CN=ccwb-credential-provider"
```

This produces two files:
- `cert.pem` — the public certificate (upload to Entra ID)
- `key.pem` — the private key (stays on the user's machine, never shared)

#### Step 5.2: Upload the certificate to Entra ID

1. In your app registration, go to **Certificates & secrets** → **Certificates**
2. Click **Upload certificate**
3. Select `cert.pem`
4. Click **Add**

#### Step 5.3: Distribute the key files to users

Each user needs both `cert.pem` and `key.pem` on their machine. Common distribution methods:

- **MDM (Intune / JAMF)**: Deploy the files to a fixed path on managed devices
- **Bundle in the `dist/` package**: Include alongside `config.json` before packaging
- **Manual**: Provide files via a secure channel and instruct users to save them locally

#### Step 5.4: Note the file paths

Decide on consistent paths for your deployment, for example:

- macOS/Linux: `~/claude-code-with-bedrock/cert.pem` and `~/claude-code-with-bedrock/key.pem`
- Windows: `%USERPROFILE%\claude-code-with-bedrock\cert.pem`

You will enter these paths when running `ccwb init`.

> **Note on absolute paths**: If you enter absolute paths during `ccwb init`, the `ccwb package` command will warn you that those paths are machine-specific and may not resolve on end-user machines with a different install layout. Prefer paths relative to the home directory (e.g. `~/claude-code-with-bedrock/cert.pem`) where possible.

#### Step 5.5: Override certificate paths on end-user machines (if needed)

If the paths recorded in `config.json` don't match the actual file locations on a user's machine, the user (or an MDM system) can override them at runtime without editing `config.json`:

```bash
# macOS / Linux — set in the shell or via a launch agent:
export AZURE_CLIENT_CERTIFICATE_PATH=~/certs/cert.pem
export AZURE_CLIENT_CERTIFICATE_KEY_PATH=~/certs/key.pem

# Windows — set as user or system environment variables:
# AZURE_CLIENT_CERTIFICATE_PATH = C:\Users\<name>\certs\cert.pem
# AZURE_CLIENT_CERTIFICATE_KEY_PATH = C:\Users\<name>\certs\key.pem
```

These env vars take precedence over the paths in `config.json` and follow the same convention as the Azure SDK.

---

## 6. Create Test Users

### Step 6.1: Navigate to Users

1. Go to **Identity** → **Users** → **All users**
2. Click **+ New user** → **Create new user**

### Step 6.2: Create a Test User

Fill in:

- **User principal name**: `testuser@yourdomain.onmicrosoft.com`
- **Display name**: `Test User`
- **Password**: Let me create the password (note it down)
- **Usage location**: Your country
- **Block sign in**: No

Click **Create**

### Step 6.3: Create Additional Users (Optional)

Repeat for more test users if needed.

---

## 7. Assign Users to Application

### Step 7.1: From Enterprise Applications

1. Go to **Identity** → **Applications** → **Enterprise applications**
2. Search for **Amazon Bedrock CLI Access**
3. Click on your application
4. Click **Users and groups**
5. Click **+ Add user/group**
6. Select your test users
7. Click **Assign**

---

## 8. Collect Required Information

You now have everything needed for deployment:

| Parameter | Your Value | Example |
|---|---|---|
| **Provider Domain** | Your tenant URL | `login.microsoftonline.com/{tenant-id}/v2.0` |
| **Client ID** | Your Application ID | `12345678-1234-1234-1234-123456789012` |
| **Client secret** *(if using Option A)* | Secret value from Step 5A | *(entered interactively during `ccwb init`)* |
| **Certificate path** *(if using Option B)* | Path to `cert.pem` on user machine | `~/claude-code-with-bedrock/cert.pem` |
| **Key path** *(if using Option B)* | Path to `key.pem` on user machine | `~/claude-code-with-bedrock/key.pem` |

### Supported Provider Domain Formats

The CLI accepts multiple formats for the Azure provider domain:

| Format | Example | Notes |
|---|---|---|
| **Full URL with /v2.0** | `login.microsoftonline.com/c56f9106-.../v2.0` | **Recommended** |
| **Full URL without /v2.0** | `login.microsoftonline.com/c56f9106-...` | Also supported |
| **Just the tenant ID** | `c56f9106-1d27-456d-bd20-3de87e595a36` | Simplest format |
| **With https:// prefix** | `https://login.microsoftonline.com/...` | Protocol stripped automatically |

> **Note**: The CLI automatically extracts the tenant ID GUID from any of these formats.

### Use the values with ccwb init

When running `ccwb init`, the wizard will ask:

```
Enter your OIDC provider domain:
> login.microsoftonline.com/{your-tenant-id}/v2.0

Enter your OIDC Client ID:
> 12345678-1234-1234-1234-123456789012

Select authentication mode:
> Public client (default, no secret required)
  Confidential client — client secret
  Confidential client — certificate (recommended for enterprise)
```

Select the mode matching your setup in Section 4–5. The wizard will prompt for the secret or certificate paths accordingly.

---

## 9. Test the Setup

### Step 9.1: Verify Application Settings

1. Go back to your app registration
2. Click **Authentication**
3. Verify:
   - Platform: **Mobile and desktop applications** (public client) or **Web** (confidential client)
   - Redirect URI: `http://localhost:8400/callback` under the correct platform
   - Public client flows: matches your chosen mode (enabled for public, disabled for confidential)

For confidential client with certificate, also verify:

4. Go to **Certificates & secrets** → **Certificates**
5. Confirm your certificate is listed and not expired

### Step 9.2: Test OIDC Discovery

```bash
curl https://login.microsoftonline.com/{your-tenant-id}/v2.0/.well-known/openid-configuration
```

Should return a JSON response with OIDC configuration.

---

## Troubleshooting

### Confidential client auth succeeds but secret or certificate is not actually validated

**Symptom**: Authentication appears to succeed even when the client secret is wrong or the certificate is not registered in Entra ID. Claude Code then fails to obtain AWS credentials.

**Cause**: The redirect URI is registered under the **Mobile and desktop applications** platform. This marks the app as a public client in Azure AD, which skips client credential enforcement entirely.

**Fix**: In your app registration → **Authentication**, remove the redirect URI from the Mobile and desktop applications platform and re-add it under **Web** (see [Step 4.1](#step-41-add-platform)). Then ensure **Allow public client flows** is set to **No**.

---

### "Reply URL does not match" Error

- Ensure redirect URI is exactly: `http://localhost:8400/callback`
- Check for trailing slashes or typos

### "User not assigned" Error

- Check user assignment in Enterprise Applications
- Verify the user account is active

### Can't Find Client ID

1. Go to **Applications** → **App registrations**
2. Click on your application
3. The Client ID is on the overview page

### "AADSTS7000218: The request body must contain the following parameter: 'client_assertion' or 'client_secret'" Error

Your tenant has `Allow public client flows = No`. You must configure a confidential client:

- Follow [Section 5](#5-confidential-client-setup-enterprise) to set up a client secret or certificate
- Re-run `ccwb init` and select the appropriate confidential client mode

### "Parameter AzureTenantId failed to satisfy constraint" Error

This error occurs during deployment if the tenant ID format is incorrect. The fix:

- **If using an older version of the CLI**: Upgrade to the latest version which supports multiple URL formats
- **Manual workaround**: When prompted for "Provider Domain", enter just your tenant ID GUID instead of the full URL:
  - ✅ Use: `c56f9106-1d27-456d-bd20-3de87e595a36`
  - ❌ Instead of: `login.microsoftonline.com/c56f9106-1d27-456d-bd20-3de87e595a36/v2.0`

### "Certificate or key file not found" Error

- Verify the paths in `config.json` match the actual file locations on this machine
- On macOS/Linux, paths starting with `~/` are expanded automatically
- If the paths differ from what was set during `ccwb init`, set `AZURE_CLIENT_CERTIFICATE_PATH` and `AZURE_CLIENT_CERTIFICATE_KEY_PATH` environment variables to override them without editing `config.json` (see [Step 5.5](#step-55-override-certificate-paths-on-end-user-machines-if-needed))
- Check file permissions: the credential provider process must be able to read both files

---

## Next Steps

Once you've completed this setup:

1. Clone the repository:
   ```bash
   git clone https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock.git
   cd claude-code-setup
   poetry install
   ```
2. Run the setup wizard: `ccwb init`
3. Create a distribution package: `ccwb package`
4. Test the deployment: `ccwb test --api`
5. Distribute the `dist/` folder to your users

---

## Security Best Practices

1. **Authentication mode**:
   - Use **certificate-based confidential client** for production — no long-lived secret is stored
   - If using a client secret, rotate it in Entra ID and re-run `--set-client-secret` on each user machine
   - Public client flows are acceptable for personal or dev tenants where enterprise policy allows it

2. **Token Settings**:
   - PKCE is always active regardless of authentication mode
   - Certificate assertions are short-lived (5-minute lifetime) and include a unique `jti` to prevent replay

3. **Certificate management**:
   - Use a 2048-bit or 4096-bit RSA key
   - Set a certificate expiry appropriate for your rotation policy (365 days is a reasonable default)
   - Plan for certificate rotation before expiry: upload the new cert to Entra ID, redistribute `cert.pem` and `key.pem`, then remove the old cert

4. **Production Considerations**:
   - Use your specific tenant ID (not "common")
   - Enable MFA for all users
   - Set appropriate session timeouts
   - Monitor sign-in logs regularly

5. **User Management**:
   - Use groups to manage access at scale
   - Regular access reviews
   - Disable unused accounts promptly
