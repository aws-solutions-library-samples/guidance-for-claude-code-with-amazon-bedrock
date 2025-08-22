# Complete Auth0 Setup Guide for Amazon Bedrock Integration

This guide walks you through setting up Auth0 from scratch to work with the AWS Cognito Identity Pool for Bedrock access.

## Table of Contents

1. [Create Auth0 Account](#1-create-auth0-account)
2. [Access Dashboard](#2-access-dashboard)
3. [Create Native Application](#3-create-native-application)
4. [Configure Application](#4-configure-application)
5. [Create Test Users](#5-create-test-users)
6. [Assign Users to Application](#6-assign-users-to-application)
7. [Collect Required Information](#7-collect-required-information)
8. [Test the Setup](#8-test-the-setup)

---

## 1. Create Auth0 Account

If you don't have an Auth0 account:

1. Go to https://auth0.com/signup
2. Fill out the registration form:
   - Email address
   - Password
   - Company (optional)
3. Click **Sign Up**
4. Choose your region (US, EU, AU, or JP)
5. Create your tenant:
   - Tenant Domain: `your-name` (becomes `your-name.auth0.com`)
   - Region: Select based on your location
6. Click **Create Account**

> **Note**: Save your tenant domain - you'll need it for configuration!

---

## 2. Access Dashboard

1. Log in to your Auth0 Dashboard at `https://manage.auth0.com`
2. You'll see the main dashboard with navigation on the left
3. Your tenant name is displayed in the top left

---

## 3. Create Native Application

### Step 3.1: Start Application Creation

1. In the Dashboard, navigate to **Applications** → **Applications**
2. Click **+ Create Application** button
3. Enter:
   - **Name**: `Amazon Bedrock CLI Access`
   - **Choose an application type**: Select **Native**
4. Click **Create**

---

## 4. Configure Application

### Step 4.1: Note the Client ID

After creation, you'll see:

- **Client ID**: Something like `aBcDeFgHiJkLmNoPqRsTuVwXyZ123456`
- **Domain**: Your tenant domain like `your-name.auth0.com`

> **Important**: Copy the Client ID - you'll need it for the configuration!

### Step 4.2: Configure Callback URLs

1. In your application settings, find **Application URIs**
2. Set **Allowed Callback URLs**:
   ```
   http://localhost:8400/callback
   ```
3. Set **Allowed Logout URLs** (optional):
   ```
   http://localhost:8400/logout
   ```

### Step 4.3: Configure Refresh Token

1. Scroll to **Refresh Token Rotation**
2. Enable **Rotation**
3. Enable **Rotation Reuse Interval** (recommended: 30 seconds)

### Step 4.4: Configure Grant Types

1. In **Advanced Settings** → **Grant Types**
2. Ensure these are enabled:
   - ✅ **Authorization Code**
   - ✅ **Refresh Token**

### Step 4.5: Save Changes

Click **Save Changes** at the bottom of the page

---

## 5. Create Test Users

### Step 5.1: Navigate to User Management

1. In the Dashboard, go to **User Management** → **Users**
2. Click **+ Create User** button

### Step 5.2: Create a Test User

Fill in the form:

- **Email**: `testuser@example.com`
- **Password**: Enter a secure password
- **Repeat Password**: Confirm the password
- **Connection**: Username-Password-Authentication (default)

Click **Create**

### Step 5.3: Create Additional Users (Optional)

Repeat to create more test users:

- `developer1@example.com`
- `developer2@example.com`

---

## 6. Assign Users to Application

By default, all users have access to all applications in Auth0. To restrict access:

### Step 6.1: Create an Action (Optional)

1. Go to **Actions** → **Flows** → **Login**
2. Click **+** → **Build Custom**
3. Name: `Restrict Bedrock Access`
4. Add code to check user email/metadata
5. Deploy the Action

### Step 6.2: Enable Organizations (Optional)

For enterprise deployments:

1. Go to **Organizations**
2. Create an organization
3. Add users to the organization
4. Enable the organization for your application

---

## 7. Collect Required Information

You now have everything needed for deployment:

| Parameter         | Your Value        | Example                            |
| ----------------- | ----------------- | ---------------------------------- |
| **Auth0Domain**   | Your Auth0 domain | `your-name.auth0.com`              |
| **Auth0ClientId** | Your Client ID    | `aBcDeFgHiJkLmNoPqRsTuVwXyZ123456` |

### Use the values with ccwb init

When running `poetry run ccwb init`, you'll be prompted for these values:

```bash
poetry run ccwb init

# The wizard will ask for:
# - Auth0 Domain: your-name.auth0.com       (your domain from above)
# - Client ID: aBcDeFgHiJkLmNoPqRsTuVwXyZ123456  (your Client ID from above)
# - AWS Region for infrastructure: us-east-1
# - Bedrock regions: us-east-1,us-west-2
# - Enable monitoring: Yes/No
```

The CLI tool will handle all the CloudFormation configuration automatically.

---

## 8. Test the Setup

### Step 8.1: Verify Application Settings

1. Go back to your application in Auth0
2. Check the **Settings** tab
3. Verify:
   - Application Type: Native
   - Allowed Callback URLs: `http://localhost:8400/callback`
   - Token Endpoint Authentication Method: None

### Step 8.2: Test OIDC Discovery

```bash
curl https://your-name.auth0.com/.well-known/openid-configuration
```

Should return a JSON response with OIDC endpoints.

### Step 8.3: Check Logs

1. Go to **Monitoring** → **Logs**
2. Look for:
   - Successful Login
   - Failed Login (for troubleshooting)

---

## Troubleshooting

### "Invalid redirect URI" Error

- Ensure the callback URL is exactly: `http://localhost:8400/callback`
- No trailing slashes or HTTPS

### "Unauthorized" Error

- Check if user exists and password is correct
- Verify application is active
- Check for any Rules or Actions blocking access

### Can't Find Client ID

1. Go to **Applications** → **Applications**
2. Click on your application
3. Client ID is at the top of the Settings tab

### Token Issues

- Ensure Authorization Code grant type is enabled
- Check that PKCE is not explicitly disabled
- Verify refresh token settings

---

## Next Steps

Once you've completed this Auth0 setup:

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

   - Enable MFA for all users
   - Use Auth0 Organizations for enterprise deployments
   - Set appropriate session and token lifetimes
   - Monitor logs regularly

2. **Token Settings**:

   - Enable refresh token rotation
   - Set token expiration to 8 hours or less
   - PKCE is automatically enabled for native apps

3. **User Management**:
   - Use Auth0's password policies
   - Enable brute-force protection
   - Set up anomaly detection
   - Regular access reviews

---

## Advanced Configuration (Optional)

### Custom Domain

For production environments:

1. Go to **Settings** → **Custom Domains**
2. Add your domain (e.g., `auth.company.com`)
3. Verify DNS settings
4. Update your application configuration

### Add Custom Claims

To include user metadata in tokens:

1. Go to **Actions** → **Flows** → **Login**
2. Create a custom Action
3. Add claims to the ID token:
   ```javascript
   exports.onExecutePostLogin = async (event, api) => {
     api.idToken.setCustomClaim('email', event.user.email);
     api.idToken.setCustomClaim(
       'department',
       event.user.user_metadata.department,
     );
   };
   ```

### Enable Enterprise Connections

For SSO with corporate identity providers:

1. Go to **Authentication** → **Enterprise**
2. Choose your connection type (SAML, OIDC, etc.)
3. Configure according to your IdP requirements
4. Enable for your application

---

## Useful Auth0 Dashboard URLs

- Dashboard: `https://manage.auth0.com/dashboard`
- Applications: `https://manage.auth0.com/dashboard/applications`
- Users: `https://manage.auth0.com/dashboard/users`
- Logs: `https://manage.auth0.com/dashboard/logs`

Remember to navigate to the correct tenant if you have multiple!
