# Complete Microsoft Entra ID Setup Guide for Amazon Bedrock Integration

This guide walks you through setting up Microsoft Entra ID from scratch to work with the AWS Cognito Identity Pool for Bedrock access.

## Table of Contents

1. [Create Azure Account](#1-create-azure-account)
2. [Access Azure Portal](#2-access-azure-portal)
3. [Create App Registration](#3-create-app-registration)
4. [Configure Authentication](#4-configure-authentication)
5. [Create Test Users](#5-create-test-users)
6. [Assign Users to Application](#6-assign-users-to-application)
7. [Collect Required Information](#7-collect-required-information)
8. [Test the Setup](#8-test-the-setup)

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

1. In your app registration, click **Authentication**
2. Click **+ Add a platform**
3. Select **Mobile and desktop applications**
4. Check **Add a custom redirect URI**
5. Enter exactly:
   ```
   http://localhost:8400/callback
   ```
6. Click **Configure**

### Step 4.2: Enable Public Client Flows

1. In Authentication, scroll to **Advanced settings**
2. Toggle **Allow public client flows** to **Yes**
3. Click **Save**

### Step 4.3: Verify API Permissions

The default `User.Read` permission is sufficient. No changes needed.

---

## 5. Create Test Users

### Step 5.1: Navigate to Users

1. Go to **Identity** → **Users** → **All users**
2. Click **+ New user** → **Create new user**

### Step 5.2: Create a Test User

Fill in:

- **User principal name**: `testuser@yourdomain.onmicrosoft.com`
- **Display name**: `Test User`
- **Password**: Let me create the password (note it down)
- **Usage location**: Your country
- **Block sign in**: No

Click **Create**

### Step 5.3: Create Additional Users (Optional)

Repeat for more test users if needed.

---

## 6. Assign Users to Application

### Step 6.1: From Enterprise Applications

1. Go to **Identity** → **Applications** → **Enterprise applications**
2. Search for **Amazon Bedrock CLI Access**
3. Click on your application
4. Click **Users and groups**
5. Click **+ Add user/group**
6. Select your test users
7. Click **Assign**

---

## 7. Collect Required Information

You now have everything needed for deployment:

| Parameter           | Your Value          | Example                                      |
| ------------------- | ------------------- | -------------------------------------------- |
| **Provider Domain** | Your tenant URL     | `login.microsoftonline.com/{tenant-id}/v2.0` |
| **Client ID**       | Your Application ID | `12345678-1234-1234-1234-123456789012`       |

### Use the values with ccwb init

When running `poetry run ccwb init`, you'll be prompted for these values:

```bash
poetry run ccwb init

# The wizard will ask for:
# - Provider Domain: login.microsoftonline.com/{your-tenant-id}/v2.0
# - Client ID: 12345678-1234-1234-1234-123456789012
# - AWS Region for infrastructure: us-east-1
# - Bedrock regions: us-east-1,us-west-2
# - Enable monitoring: Yes/No
```

The CLI tool will handle all the CloudFormation configuration automatically.

---

## 8. Test the Setup

### Step 8.1: Verify Application Settings

1. Go back to your app registration
2. Click **Authentication**
3. Verify:
   - Platform: Mobile and desktop applications
   - Redirect URI: `http://localhost:8400/callback`
   - Public client flows: Enabled

### Step 8.2: Test OIDC Discovery

```bash
curl https://login.microsoftonline.com/{your-tenant-id}/v2.0/.well-known/openid-configuration
```

Should return a JSON response with OIDC configuration.

---

## Troubleshooting

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

---

## Next Steps

Once you've completed this setup:

1. Clone the repository:
   ```bash
   git clone https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock.git
   cd claude-code-setup
   poetry install
   ```
2. Run the setup wizard: `poetry run ccwb init`
3. Create a distribution package: `poetry run ccwb package`
4. Test the deployment: `poetry run ccwb test --api`
5. Distribute the `dist/` folder to your users

---

## Security Best Practices

1. **Production Considerations**:

   - Use your specific tenant ID (not "common")
   - Enable MFA for all users
   - Set appropriate session timeouts
   - Monitor sign-in logs regularly

2. **Token Settings**:
   - PKCE is enabled by default for native apps
   - Public client flows must be enabled
3. **User Management**:
   - Use groups to manage access at scale
   - Regular access reviews
   - Disable unused accounts promptly
