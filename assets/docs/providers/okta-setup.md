# Complete Okta Setup Guide for Amazon Bedrock Integration

This guide walks you through setting up Okta from scratch to work with the AWS Cognito Identity Pool for Bedrock access.

## Table of Contents

1. [Create Okta Developer Account](#1-create-okta-developer-account)
2. [Access Admin Console](#2-access-admin-console)
3. [Create OIDC Application](#3-create-oidc-application)
4. [Create Test Users](#4-create-test-users)
5. [Assign Users to Application](#5-assign-users-to-application)
6. [Collect Required Information](#6-collect-required-information)
7. [Test the Setup](#7-test-the-setup)
8. [Quota Monitoring Configuration](#8-quota-monitoring-configuration-optional)

---

## 1. Create Okta Developer Account

If you don't have an Okta account:

1. Go to https://developer.okta.com/signup/
2. Fill out the registration form:
   - First Name
   - Last Name
   - Email (this will be your admin username)
   - Country
3. Click **Sign Up**
4. Check your email for the activation link
5. Click the activation link and set your password
6. You'll receive your Okta domain (e.g., `dev-12345678.okta.com`)

> **Note**: Save your Okta domain - you'll need it for the CloudFormation parameters!

---

## 2. Access Admin Console

1. Log in to your Okta organization at `https://your-domain.okta.com`
2. Click **Admin** in the top right corner to access the Admin Console
3. You should see the Dashboard with various menu options on the left

---

## 3. Create OIDC Application

### Step 3.1: Start Application Creation

1. In the Admin Console, navigate to **Applications** → **Applications**
2. Click **Create App Integration** button
3. Select:
   - **Sign-in method**: OIDC - OpenID Connect
   - **Application type**: Native Application
4. Click **Next**

### Step 3.2: Configure Application Settings

Fill in the following settings:

#### General Settings

- **App integration name**: `Amazon Bedrock CLI Access` (or your preferred name)
- **Logo**: Optional - you can skip this

#### Grant Type

Make sure these are checked:

- ✅ **Authorization Code**
- ✅ **Refresh Token**
- ✅ **Resource Owner Password** (optional, for testing)

#### Sign-in Redirect URIs

Add this exact URI:

```
http://localhost:8400/callback
```

#### Sign-out Redirect URIs (optional)

```
http://localhost:8400/logout
```

#### Controlled Access

- Select **Allow everyone in your organization to access**
- Or select **Limit access to selected groups** if you want to restrict access

### Step 3.3: Save the Application

1. Click **Save**
2. You'll be taken to the application settings page

### Step 3.4: Note the Client ID

After saving, you'll see:

- **Client ID**: Something like `0oa1234567890abcde`
- **Okta domain**: Your domain like `dev-12345678.okta.com`

> **Important**: Copy the Client ID - you'll need it for the CloudFormation parameters!

---

## 4. Create Test Users

### Step 4.1: Navigate to Users

1. In the Admin Console, go to **Directory** → **People**
2. Click **Add Person** button

### Step 4.2: Create a Test User

Fill in the form:

- **First name**: Test
- **Last name**: User
- **Username**: testuser@example.com (must be email format)
- **Primary email**: testuser@example.com
- **Password**: Select **Set by admin** and enter a password
- ✅ **User must change password on first login** (optional)
- ❌ **Send user activation email now** (uncheck for testing)

Click **Save**

### Step 4.3: Create Additional Users (Optional)

Repeat the process to create more test users:

- `developer1@example.com`
- `developer2@example.com`
- etc.

---

## 5. Assign Users to Application

### Method 1: From the Application (Recommended)

1. Go to **Applications** → **Applications**
2. Click on your **Amazon Bedrock CLI Access** application
3. Click the **Assignments** tab
4. Click **Assign** → **Assign to People**
5. Find your test user(s) in the list
6. Click **Assign** next to each user
7. Click **Save and Go Back**
8. Click **Done**

### Method 2: From the User Profile

1. Go to **Directory** → **People**
2. Click on a user (e.g., `testuser@example.com`)
3. Click the **Applications** tab
4. Click **Assign Applications**
5. Find and select **Amazon Bedrock CLI Access**
6. Click **Assign**
7. Click **Save and Go Back**

---

## 6. Collect Required Information

You now have everything needed for the CloudFormation deployment:

| Parameter        | Your Value       | Example                 |
| ---------------- | ---------------- | ----------------------- |
| **OktaDomain**   | Your Okta domain | `dev-12345678.okta.com` |
| **OktaClientId** | Your Client ID   | `0oa1234567890abcde`    |

### Use the values with ccwb init

When running `poetry run ccwb init`, you'll be prompted for these values:

```bash
poetry run ccwb init

# The wizard will ask for:
# - Okta Domain: dev-12345678.okta.com    (your domain from above)
# - Client ID: 0oa1234567890abcde         (your Client ID from above)
# - AWS Region for infrastructure: us-east-1
# - Bedrock regions: us-east-1,us-west-2
# - Enable monitoring: Yes/No
```

The CLI tool will handle all the CloudFormation configuration automatically.

---

## 7. Test the Setup

### Step 7.1: Verify Application Settings

1. Go back to your application in Okta
2. Click the **General** tab
3. Verify:
   - Client authentication: **Use PKCE**
   - Redirect URIs include: `http://localhost:8400/callback`
   - Grant types include: Authorization Code and Refresh Token

### Step 7.2: Test User Assignment

1. Go to **Reports** → **System Log**
2. Look for entries like:
   - "User single sign on to app"
   - "Add user to application membership"
3. These should show **Success** status

---

## Advanced Configuration (Optional)

### Enable Refresh Token Rotation

1. In your application, go to **General** tab
2. Click **Edit** in the General Settings section
3. Under **Refresh Token**, select:
   - **Rotate token after every use**
   - Grace period: **30 seconds** (or your preference)
4. Click **Save**

### Add Custom Claims (Optional)

If you want to add department or group information:

1. Go to **Security** → **API**
2. Click on your Authorization Server (usually "default")
3. Click **Claims** tab
4. Click **Add Claim**
5. Configure:
   - **Name**: `department`
   - **Include in**: ID Token, Access Token
   - **Value type**: Expression
   - **Value**: `user.department`
6. Click **Create**

### Set Up Groups (Optional)

1. Go to **Directory** → **Groups**
2. Click **Add Group**
3. Name: `bedrock-users`
4. Description: `Users with Amazon Bedrock access`
5. Add users to this group
6. Assign the group to your application

---

## 8. Quota Monitoring Configuration (Optional)

If you're using the quota monitoring feature to track and limit user token usage, additional Okta configuration is required.

### Required JWT Scopes

The quota monitoring API requires these scopes in your JWT tokens:

| Scope | Required? | Purpose |
|-------|-----------|---------|
| `openid` | **Yes** | Base OIDC scope |
| `email` | **Yes** | User email for quota tracking |
| `profile` | Recommended | User profile information |
| `groups` | Optional | Group membership for group-based quotas |

> **Note**: The `groups` scope is only needed if you want to use group-based quota policies (e.g., different limits for `engineering` vs `data-science` teams).

### Adding the Groups Scope

1. Go to **Security** → **API** → **Authorization Servers**
2. Click on your authorization server (usually "default")
3. Click the **Scopes** tab
4. Click **Add Scope**
5. Configure:
   - **Name**: `groups`
   - **Display phrase**: `Access your group memberships`
   - **Description**: `Allows the app to see your group memberships`
   - **User consent**: `Implicit`
6. Click **Create**

### Configuring the Groups Claim

To include group membership in JWT tokens:

1. Go to **Security** → **API** → **Authorization Servers**
2. Click on your authorization server (usually "default")
3. Click the **Claims** tab
4. Click **Add Claim**
5. Configure:
   - **Name**: `groups`
   - **Include in token type**: `ID Token` → `Always`
   - **Value type**: `Groups`
   - **Filter**: `Matches regex` → `.*` (includes all groups)
   - **Include in**: `Any scope` (or select specific scopes)
6. Click **Create**

### Token Lifetime Settings

Token lifetimes affect how often quota checks occur:

1. Go to **Security** → **API** → **Authorization Servers**
2. Click on your authorization server
3. Click the **Access Policies** tab
4. Click on your policy, then edit the rule
5. Configure token lifetimes:
   - **Access token lifetime**: `1 hour` (default, works well)
   - **ID token lifetime**: `1 hour` (default)
   - **Refresh token lifetime**: As needed for your use case

> **Tip**: Shorter token lifetimes mean more frequent quota checks but more re-authentication. The defaults work well for most use cases.

### Creating Groups for Quota Policies

If using group-based quotas:

1. Go to **Directory** → **Groups**
2. Click **Add Group**
3. Create groups matching your quota policy needs:
   - `engineering` - Engineering team
   - `data-science` - Data science team
   - `power-users` - Users with higher limits
4. Assign users to appropriate groups
5. Assign groups to your Bedrock CLI application

### Deploy and Configure Quota Monitoring

After completing Okta configuration:

```bash
# Deploy the quota monitoring stack
poetry run ccwb deploy quota

# Set a default quota for all users (required)
poetry run ccwb quota set-default --monthly-limit 225M

# Optional: Set group-based quotas (requires groups claim)
poetry run ccwb quota set-group engineering --monthly-limit 500M
poetry run ccwb quota set-group data-science --monthly-limit 1B

# Optional: Set user-specific quotas
poetry run ccwb quota set-user power.user@company.com --monthly-limit 500M

# Test the quota API
poetry run ccwb test quota-api
```

### Verifying Your Configuration

Test that your JWT includes the expected claims:

1. Complete an authentication flow with your application
2. Decode the ID token at [jwt.io](https://jwt.io)
3. Verify these claims are present:
   - `email` - Your user's email address
   - `groups` - Array of group names (if configured)

For complete quota monitoring documentation, see [Quota Monitoring Guide](../QUOTA_MONITORING.md).

---

## Troubleshooting

### "Invalid redirect URI" Error

- Ensure the redirect URI is exactly: `http://localhost:8400/callback`
- Check for trailing slashes or typos

### User Can't Sign In

- Verify the user is assigned to the application
- Check if the user's account is active
- Ensure password meets Okta's policy requirements

### Can't Find Client ID

1. Go to **Applications** → **Applications**
2. Click on your application
3. The Client ID is on the **General** tab under "Client Credentials"

---

## Next Steps

Once you've completed this Okta setup:

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

   - Use groups to manage access at scale
   - Enable MFA for all users
   - Set appropriate session timeouts
   - Monitor the System Log regularly

2. **Token Settings**:

   - Enable refresh token rotation
   - Set reasonable token lifetimes
   - Use PKCE (enabled by default for native apps)

3. **User Management**:
   - Use Okta's password policies
   - Implement account lockout policies
   - Regular access reviews

---

## Useful Okta Admin URLs

- Dashboard: `https://your-domain.okta.com/admin/dashboard`
- Applications: `https://your-domain.okta.com/admin/apps/active`
- Users: `https://your-domain.okta.com/admin/users`
- System Log: `https://your-domain.okta.com/admin/reports/system_log`

Remember to replace `your-domain` with your actual Okta domain!
