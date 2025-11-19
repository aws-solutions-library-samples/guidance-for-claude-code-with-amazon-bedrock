# Distribution Deployment Guide

Complete guide for deploying Claude Code package distribution using either presigned S3 URLs (simple) or authenticated landing pages (enterprise).

---

## Overview

Claude Code with Bedrock supports **two distribution methods** for sharing packaged binaries and settings with end users:

1. **Presigned S3 URLs** - Simple distribution via time-limited URLs, no authentication required
2. **Authenticated Landing Page** - Enterprise-grade distribution with IdP authentication via ALB + Lambda

**Choosing the right distribution type:** See [comparison.md](./comparison.md) for detailed comparison, cost analysis, and decision guidance.

### Architecture Overview

#### Presigned S3 Distribution

```
Admin Machine → S3 Bucket → Presigned URL (7 days) → Users download directly
```

- **Components**: S3 bucket + IAM user with presigned URL generation
- **Authentication**: None (URL-based access)
- **Best for**: Small teams (<20 users), internal trusted users

#### Landing Page Distribution

```
User → ALB (HTTPS) → OIDC Authentication (IdP) → Lambda → S3 (presigned URLs)
```

- **Components**: ALB + Lambda + S3 + VPC + Security Groups
- **Authentication**: IdP (Okta/Azure/Auth0/Cognito) via OIDC
- **Best for**: Large teams (20-100 users), enterprise compliance requirements

---

## Prerequisites

### Common Prerequisites (Both Distribution Types)

- **AWS CLI**: Installed and configured with credentials
- **Python 3.10+**: Required for ccwb CLI
- **Poetry**: Python package manager (`curl -sSL https://install.python-poetry.org | python3 -`)
- **Basic Authentication Configured**: Must have completed `ccwb init` for Bedrock authentication
- **Packages Built**: Run `ccwb package` to create distribution packages

### Landing Page Additional Prerequisites

- **VPC with Subnets**:

  - Public subnets in 2+ availability zones (for ALB)
  - Private subnets in 2+ availability zones (for Lambda)
  - Can be created via `ccwb deploy networking` or use existing VPC

- **IdP Account with Admin Access**:

  - Ability to create web applications (OAuth2 confidential clients)
  - Access to client secrets
  - Ability to configure redirect URIs

- **Understanding of OAuth2/OIDC**:
  - Authorization code flow
  - Client credentials (ID + secret)
  - Redirect URIs / callback URLs

---

## Presigned-S3 Distribution Deployment

Simple distribution workflow for small teams with no authentication requirements.

### Step 1: Initialize Distribution Configuration

Run the init wizard and select presigned S3 distribution:

```bash
poetry run ccwb init
```

When prompted for distribution method:

- Select: **"Presigned S3 URLs (simple, no authentication)"**

The wizard will:

- Configure distribution settings in your profile
- Save configuration to `~/.ccwb/profiles/<profile-name>.json`

### Step 2: Deploy Distribution Stack

Deploy the presigned-s3 distribution infrastructure:

```bash
poetry run ccwb deploy distribution
```

This creates:

- **S3 Bucket**: `{identity-pool-name}-dist-{account-id}`
- **IAM User**: With permissions to generate presigned URLs
- **Secrets Manager Secret**: Stores IAM user credentials

**Deployment time**: ~2-3 minutes

### Step 3: Build Packages

Build packages for all platforms:

```bash
poetry run ccwb package --target-platform all
```

This creates executables in `dist/` directory:

- `credential-process-macos-arm64`
- `credential-process-macos-intel`
- `credential-process-linux-x64`
- `credential-process-linux-arm64`
- `credential-process-windows.exe`
- Installation scripts and configuration

### Step 4: Distribute Packages

Upload packages and generate presigned URLs:

```bash
poetry run ccwb distribute
```

Output includes:

- **Presigned URL**: Valid for 7 days (or custom expiry via `--expires-hours`)
- **SHA256 Checksum**: For package integrity verification
- **Download Instructions**: For macOS/Linux and Windows
- **File Size**: Package size information

### Step 5: Share with Users

**Copy the presigned URL and share via:**

- Messaging App
- Email
- Internal documentation

**URL expires after 7 days** - regenerate by running `ccwb distribute` again.

**Retrieve latest URL** without regenerating:

```bash
poetry run ccwb distribute --get-latest
```

### Presigned-S3 Stack Outputs

View stack outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name {identity-pool-name}-distribution \
  --query 'Stacks[0].Outputs'
```

Key outputs:

- `DistributionBucket`: S3 bucket name
- `IAMUserName`: IAM user for presigned URL generation
- `IAMUserAccessKeySecretArn`: Secrets Manager ARN for credentials

---

## Landing-Page Distribution Deployment

Enterprise distribution with IdP authentication. **Critical**: IdP web application must be configured BEFORE and AFTER deployment.

### Deployment Overview

The landing page deployment requires a **two-phase IdP configuration**:

1. **Phase 1 (BEFORE)**: Create web application in IdP with placeholder redirect URI
2. **Phase 2 (DURING)**: Deploy infrastructure via ccwb
3. **Phase 3 (AFTER)**: Update IdP redirect URI with actual ALB DNS/domain

This is necessary because:

- CloudFormation needs client ID/secret to deploy ALB OIDC
- ALB DNS name is only known AFTER deployment
- IdP redirect URI must match ALB DNS exactly

---

### Phase 1: IdP Web Application Setup (BEFORE ccwb init)

You must create a **web application** (OAuth2 confidential client) in your IdP. This is **separate** from the native CLI app.

#### Why Two Separate Applications?

|                  | CLI Native App                   | Distribution Web App                   |
| ---------------- | -------------------------------- | -------------------------------------- |
| **OAuth2 Flow**  | Authorization Code + PKCE        | Authorization Code                     |
| **Client Type**  | Public (no secret)               | Confidential (with secret)             |
| **Redirect URI** | `http://localhost:8400/callback` | `https://<alb-dns>/oauth2/idpresponse` |
| **Used By**      | CLI credential process           | ALB OIDC authentication                |
| **Created When** | During first ccwb init           | Before distribution setup              |

---

#### Okta Web Application Setup

1. **Navigate to Applications**:

   - Okta Admin Console → Applications → Applications → Create App Integration

2. **Create OIDC Web Application**:

   - Sign-in method: **"OIDC - OpenID Connect"**
   - Application type: **"Web Application"**
   - Click **Next**

3. **Configure Application Settings**:

   - **App integration name**: `Claude Code Distribution`
   - **Grant type**: ✅ Authorization Code, ✅ Refresh Token
   - **Sign-in redirect URIs**:
     - `https://placeholder.example.com/oauth2/idpresponse` (temporary - will update after deployment)
   - **Sign-out redirect URIs**:
     - `https://placeholder.example.com` (temporary)
   - **Controlled access**: Configure based on your organization's needs
   - Click **Save**

4. **Copy Credentials**:

   - **Client ID**: Copy from General tab
   - **Client Secret**: Copy from General tab (click Show to reveal)
   - **Okta Domain**: Your Okta domain (e.g., `company.okta.com`)

5. **Assign Users/Groups** (Optional):
   - Assignments tab → Assign to users or groups who should access distribution

**Post-Deployment (Phase 3)**: Return here to update redirect URIs with actual ALB DNS.

---

#### Azure AD / Entra ID Web Application Setup

1. **Navigate to App Registrations**:

   - Azure Portal → Azure Active Directory → App registrations → New registration

2. **Register Application**:

   - **Name**: `Claude Code Distribution`
   - **Supported account types**: **"Accounts in this organizational directory only (Single tenant)"**
   - **Redirect URI**:
     - Platform: **Web**
     - URL: `https://placeholder.example.com/oauth2/idpresponse` (temporary)
   - Click **Register**

3. **Copy Tenant and Client IDs**:

   - Overview page → Copy:
     - **Application (client) ID**: This is your client ID
     - **Directory (tenant) ID**: This is your tenant ID

4. **Create Client Secret**:

   - Left menu → **Certificates & secrets** → **Client secrets** tab
   - Click **New client secret**
   - Description: `Claude Code Distribution Landing Page`
   - Expires: Choose expiration (recommend 24 months)
   - Click **Add**
   - **Copy the secret value immediately** (won't be shown again)

5. **Configure API Permissions** (if needed):
   - Left menu → **API permissions**
   - Ensure OpenID Connect permissions are granted

**Post-Deployment (Phase 3)**: Return to Authentication tab to update redirect URI.

---

#### Auth0 Web Application Setup

1. **Navigate to Applications**:

   - Auth0 Dashboard → Applications → Applications → Create Application

2. **Create Application**:

   - **Name**: `Claude Code Distribution`
   - **Application type**: **"Regular Web Applications"**
   - Click **Create**

3. **Configure Settings**:

   - Settings tab:
     - **Allowed Callback URLs**:
       - `https://placeholder.example.com/oauth2/idpresponse` (temporary)
     - **Allowed Logout URLs**:
       - `https://placeholder.example.com` (temporary)
     - **Allowed Web Origins**: Leave empty
   - Click **Save Changes**

4. **Copy Credentials**:

   - Settings tab → Basic Information:
     - **Domain**: Your Auth0 domain (e.g., `company.auth0.com` or `company.us.auth0.com`)
     - **Client ID**: Copy value
     - **Client Secret**: Copy value

5. **Configure Connections** (Optional):
   - Connections tab → Enable enterprise connections (e.g., SAML, Active Directory)

**Post-Deployment (Phase 3)**: Return to Settings tab to update callback URLs.

---

#### Cognito User Pool Web Client Setup

**✨ AUTOMATED**: Cognito configuration is now fully automated with zero copy-paste!

**Prerequisites**:

- Cognito User Pool deployed via `cognito-user-pool-setup.yaml` (latest version)
- Latest template includes `DistributionWebClient` + auto-secret-storage

##### Step 1: Deploy/Update Cognito Stack

Ensure you're using the latest template with distribution support:

```bash
aws cloudformation deploy \
  --template-file deployment/infrastructure/cognito-user-pool-setup.yaml \
  --stack-name <your-cognito-stack-name> \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    UserPoolName=<your-pool-name> \
    DomainPrefix=<your-domain-prefix>
```

**What this creates**:

- ✅ User Pool with CLI native app client (existing)
- ✅ Distribution web app client with client secret (NEW)
- ✅ Client secret automatically stored in Secrets Manager (NEW)
- ✅ All outputs available for auto-detection (NEW)

**Deployment time**: ~3-5 minutes

##### Step 2: Configuration is Automatic!

When you run `poetry run ccwb init` (Phase 2), the wizard will:

1. **Auto-detect** your Cognito stack
2. **Validate** it has distribution support
3. **Display** detected configuration:

   ```
   ✓ Found Cognito stack: my-cognito-stack
   ✓ Stack has all required outputs for distribution

   Detected Configuration:
     • User Pool ID: us-east-1_ABC123XYZ
     • Domain: my-company
     • Client ID: 7a8b9c0d1e2f3g4h
     • Secret ARN: arn:aws:secretsmanager:...

   Use these detected values? [Y/n] █
   ```

4. **Press Enter** → Configuration complete! No copy-paste needed.

**That's it!** Cognito configuration is automated through stack outputs.

---

### Phase 2: Initialize and Deploy Distribution

Now that you have IdP web application credentials, configure and deploy the landing page.

#### Step 2.1: Initialize Distribution Configuration

Run the init wizard:

```bash
poetry run ccwb init
```

When prompted for distribution method:

- Select: **"Authenticated Landing Page (IdP + ALB)"**

**IdP Configuration Prompts**:

1. **Identity provider for web authentication**:
   - Select your IdP: Okta / Azure AD / Auth0 / Cognito

**For Cognito**: Auto-detection takes over! ✨

- Wizard searches for Cognito stack
- Displays detected configuration (User Pool ID, Domain, Client ID, Secret ARN)
- You press Enter to accept → Done! (Skip to Custom Domain prompt)

**For Okta/Azure/Auth0**: Manual entry required

2. **IdP Domain** (Okta/Azure/Auth0 only):

   - **Okta**: `company.okta.com` (your Okta domain)
   - **Azure**: Tenant ID (GUID from Azure app registration)
   - **Auth0**: `company.auth0.com` (your Auth0 domain)

3. **IdP Web Application Client ID** (Okta/Azure/Auth0 only):

   - Enter the client ID from Phase 1

4. **IdP Web Application Client Secret** (Okta/Azure/Auth0 only):

   - Enter the client secret directly (will be stored in Secrets Manager automatically)

5. **Custom Domain** (Optional, all providers):
   - Enable custom domain? (yes/no)
   - If yes:
     - Custom domain name: `downloads.company.com`
     - Route53 hosted zone ID: (if using Route53 for DNS)

The wizard will:

- **For Cognito**: Auto-populate from stack outputs (zero copy-paste!)
- **For others**: Store client secret in AWS Secrets Manager automatically
- Save configuration to `~/.ccwb/profiles/<profile-name>.json`
- Set `distribution_type = "landing-page"`

#### Step 2.2: Deploy VPC (if needed)

Landing page requires VPC with public/private subnets in 2+ availability zones.

**Option A: Use existing VPC/subnets**

- Ensure VPC has public subnets in 2+ AZs (for ALB)
- Ensure VPC has private subnets in 2+ AZs (for Lambda)
- Make note of VPC ID and subnet IDs

**Option B: Create new VPC via ccwb**:

```bash
poetry run ccwb deploy networking
```

This creates:

- VPC with CIDR `10.0.0.0/16`
- 2 public subnets in different AZs
- 2 private subnets in different AZs
- Internet Gateway
- NAT Gateway (for Lambda internet access)
- Route tables

**Deployment time**: ~3-5 minutes

#### Step 2.3: Deploy Landing Page Stack

Deploy the authenticated landing page infrastructure:

```bash
poetry run ccwb deploy distribution
```

This creates:

- **S3 Bucket**: For package storage
- **Lambda Function**: Generates landing page HTML and presigned URLs
- **ALB**: Internet-facing load balancer with HTTPS listener
- **Security Groups**: ALB ingress (port 443) and Lambda egress
- **Target Group**: Routes ALB traffic to Lambda
- **ACM Certificate**: If custom domain specified (auto-validated via Route53)
- **Route53 Record**: If custom domain with Route53 specified
- **OIDC Configuration**: ALB authenticates via IdP before forwarding to Lambda

**Deployment time**: ~5-10 minutes

#### Step 2.4: Capture Stack Outputs

After deployment completes, get the stack outputs:

```bash
poetry run ccwb deploy distribution
```

The deployment will display:

```
✓ Landing page deployed successfully!

Distribution URL: https://<alb-dns-name>

⚠️  Configure your IdP web application:
   Redirect URI: https://<alb-dns-name>/oauth2/idpresponse

   Add this redirect URI to your IdP web application settings before users can authenticate.
```

Or query directly:

```bash
aws cloudformation describe-stacks \
  --stack-name {identity-pool-name}-distribution \
  --query 'Stacks[0].Outputs'
```

Key outputs:

- **DistributionURL**: Landing page URL (ALB DNS or custom domain)
- **IdPRedirectURI**: Callback URL to configure in IdP
- **DistributionBucket**: S3 bucket name for packages

**Copy the `IdPRedirectURI` value** - you'll need it in Phase 3.

---

### Phase 3: Post-Deployment IdP Configuration

**CRITICAL**: You must update the IdP redirect URI with the actual ALB DNS before authentication will work.

#### Update Okta Redirect URI

1. **Okta Admin Console** → Applications → Applications
2. Select **"Claude Code Distribution"** application
3. **General** tab → Edit **General Settings**
4. **Sign-in redirect URIs**:
   - Remove: `https://placeholder.example.com/oauth2/idpresponse`
   - Add: `https://<actual-alb-dns>/oauth2/idpresponse` (from stack outputs)
5. **Sign-out redirect URIs**:
   - Remove: `https://placeholder.example.com`
   - Add: `https://<actual-alb-dns>` (from stack outputs)
6. Click **Save**

#### Update Azure AD Redirect URI

1. **Azure Portal** → Azure Active Directory → App registrations
2. Select **"Claude Code Distribution"** application
3. **Authentication** (left menu)
4. **Web** → Redirect URIs:
   - Remove: `https://placeholder.example.com/oauth2/idpresponse`
   - Add: `https://<actual-alb-dns>/oauth2/idpresponse` (from stack outputs)
5. Click **Save**

#### Update Auth0 Callback URLs

1. **Auth0 Dashboard** → Applications → Applications
2. Select **"Claude Code Distribution"** application
3. **Settings** tab
4. **Allowed Callback URLs**:
   - Remove: `https://placeholder.example.com/oauth2/idpresponse`
   - Add: `https://<actual-alb-dns>/oauth2/idpresponse` (from stack outputs)
5. **Allowed Logout URLs**:
   - Remove: `https://placeholder.example.com`
   - Add: `https://<actual-alb-dns>` (from stack outputs)
6. Click **Save Changes**

#### Update Cognito Callback URLs

Using AWS CLI:

```bash
aws cognito-idp update-user-pool-client \
  --user-pool-id <user-pool-id> \
  --client-id <distribution-web-client-id> \
  --callback-urls "https://<actual-alb-dns>/oauth2/idpresponse" \
  --logout-urls "https://<actual-alb-dns>"
```

Or via AWS Console:

1. **AWS Console** → Cognito → User Pools
2. Select your User Pool
3. **App integration** → App clients → Select **distribution-web-client**
4. **Hosted UI** → Edit:
   - **Allowed callback URLs**: Update to `https://<actual-alb-dns>/oauth2/idpresponse`
   - **Allowed sign-out URLs**: Update to `https://<actual-alb-dns>`
5. **Save changes**

---

### Phase 4: Publish and Share Packages

#### Step 4.1: Build Packages

Build packages for all platforms:

```bash
poetry run ccwb package --target-platform all
```

#### Step 4.2: Distribute Packages

Upload packages to the landing page:

```bash
poetry run ccwb distribute
```

Output for landing-page type:

```
✓ Packages published to landing page!

Users can download from: https://<alb-dns-or-custom-domain>
```

The command uploads packages to S3 but does NOT generate presigned URLs. Users will access the landing page which generates presigned URLs dynamically after authentication.

#### Step 4.3: Share Landing Page URL

**Share the permanent landing page URL via:**

- Internal wiki/documentation
- Slack channel
- Email distribution list
- Onboarding documentation

**Users will**:

1. Navigate to the landing page URL
2. Be redirected to IdP for authentication
3. Authenticate with corporate credentials
4. View landing page with download buttons
5. Click download (presigned URL generated on-the-fly, expires in 1 hour)

**No need to regenerate URLs** - the landing page URL is permanent. Only update packages by running `ccwb distribute` when you have new versions.

---

### Phase 5: Test the Landing Page

1. **Navigate to landing page URL** in your browser

2. **Expected**: Redirect to IdP login page

3. **Authenticate** with your corporate credentials

4. **Expected**: Landing page displays:

   - "Welcome, [your-email]"
   - Release date
   - Platform-specific download buttons (Windows, Linux, macOS, All Platforms)
   - File sizes
   - Installation instructions

5. **Click download** for your platform

6. **Expected**: Package downloads immediately

7. **Verify checksum** (optional):
   ```bash
   sha256sum <downloaded-file>
   ```

#### If Authentication Fails

**400 Bad Request**:

- **Cause**: IdP redirect URI not configured or mismatch
- **Fix**: Verify IdP callback URL exactly matches `IdPRedirectURI` from stack outputs

**OIDC Error / Invalid State**:

- **Cause**: Client secret mismatch
- **Fix**: Verify Secrets Manager secret value matches IdP client secret

**401 Unauthorized**:

- **Cause**: User not assigned to IdP application
- **Fix**: Assign user to IdP application in IdP console

**Redirect Loop**:

- **Cause**: Cookie issues or session configuration
- **Fix**: Clear browser cookies, verify ALB session timeout settings

---

## Publishing Packages

Both distribution types use the same publishing workflow.

### Build Packages

Build executables for all platforms:

```bash
poetry run ccwb package --target-platform all
```

Or build for specific platforms:

```bash
# macOS only
poetry run ccwb package --target-platform macos

# Windows only (requires CodeBuild)
poetry run ccwb package --target-platform windows

# Linux only
poetry run ccwb package --target-platform linux
```

Packages are created in `dist/` directory:

- Credential process executables for each platform
- OTEL helper executables (if monitoring enabled)
- Installation scripts (`install.sh`, `install.bat`)
- Configuration file (`config.json`)
- Claude Code settings directory (if configured)

### Distribute Packages

Upload packages and generate distribution URLs:

```bash
poetry run ccwb distribute
```

**For presigned-s3**:

- Uploads package to S3
- Generates presigned URL (7-day expiry)
- Displays URL and download instructions
- Admin shares URL with users

**For landing-page**:

- Uploads packages to S3
- Displays landing page URL
- Admin shares landing page URL with users
- Users authenticate and download

### Custom Expiry (Presigned-S3 Only)

Set custom expiry time (1-168 hours):

```bash
# 48 hours (default)
poetry run ccwb distribute --expires-hours 48

# 1 hour (minimum)
poetry run ccwb distribute --expires-hours 1

# 7 days (168 hours, maximum)
poetry run ccwb distribute --expires-hours 168
```

**Note**: IAM user presigned URLs have a maximum lifetime of 7 days (168 hours).

### Retrieve Latest URL (Presigned-S3 Only)

Get the latest presigned URL without regenerating:

```bash
poetry run ccwb distribute --get-latest
```

Displays:

- Current presigned URL
- Expiration time
- Package filename and checksum
- Download instructions

---

## Switching Distribution Types

You can switch between presigned-s3 and landing-page at any time.

### Process

1. **Reconfigure profile**:

   ```bash
   poetry run ccwb init
   ```

   - Select different distribution type
   - Complete configuration (IdP setup if switching to landing-page)

2. **Redeploy distribution stack**:

   ```bash
   poetry run ccwb deploy distribution
   ```

   - CloudFormation will **replace** the existing stack with new type
   - Old stack resources (S3 bucket, IAM user, etc.) will be **deleted**
   - New stack resources will be **created**

3. **Publish packages** to new distribution:
   ```bash
   poetry run ccwb package
   poetry run ccwb distribute
   ```

### Important Notes

- **Cannot have both deployed simultaneously**: Both types use same stack name (`{identity-pool-name}-distribution`)
- **Existing packages will be deleted**: S3 bucket is deleted and recreated
- **Backup packages if needed**: Download from S3 before switching
- **Update user instructions**: If switching to landing-page, users need new URL and IdP credentials

---

## Post-Deployment Operations

### Updating Packages

To publish new package versions:

1. **Build new packages**:

   ```bash
   poetry run ccwb package --target-platform all
   ```

2. **Upload to distribution**:

   ```bash
   poetry run ccwb distribute
   ```

3. **Notify users**:
   - **Presigned-S3**: Share new URL (old URL still valid until expiry)
   - **Landing-Page**: No action needed (users refresh landing page for new release date)

**No stack redeployment required** for package updates.

---

### Adding Custom Domain (Landing-Page)

#### Prerequisites

- Route53 hosted zone for your domain
- Domain name (e.g., `downloads.company.com`)
- Hosted zone ID

#### Process

1. **Reconfigure with custom domain**:

   ```bash
   poetry run ccwb init
   ```

   - When prompted for custom domain: **yes**
   - Enter domain name: `downloads.company.com`
   - Enter hosted zone ID: `Z1234567890ABC`

2. **Redeploy distribution stack**:

   ```bash
   poetry run ccwb deploy distribution
   ```

   - Creates ACM certificate
   - Validates certificate via DNS (automatic with Route53)
   - Creates Route53 A record pointing to ALB
   - Updates ALB listener with ACM certificate

3. **Update IdP redirect URI** with custom domain:

   - Update callback URL from `https://<alb-dns>/oauth2/idpresponse` to `https://downloads.company.com/oauth2/idpresponse`
   - Follow Phase 3 instructions for your IdP

4. **Test**:
   - Navigate to `https://downloads.company.com`
   - Verify SSL certificate valid
   - Verify IdP authentication works

**DNS propagation**: 2-5 minutes for Route53

---

## Security Considerations

### Distribution Type Comparison

**Presigned-S3**: Time-limited URLs (7-day expiry), no authentication, suitable for internal trusted users only. URLs can be shared/leaked with no access revocation.

**Landing-Page**: IdP authentication required, short-lived presigned URLs (1-hour expiry), ALB access logs for audit trail, suitable for enterprise compliance.

### Best Practices

- Store all credentials in AWS Secrets Manager
- Verify package integrity using SHA256 checksums
- For landing-page: Enable MFA, rotate secrets every 90 days, restrict IdP app assignment
- Monitor downloads via S3/ALB access logs

---

## Reference Links

- **Distribution Comparison**: [comparison.md](./comparison.md) - Detailed comparison of presigned-s3 vs landing-page
- **IdP Provider Setup**: [../providers/](../providers/) - IdP-specific CLI authentication guides
- **Main Deployment Guide**: [../../DEPLOYMENT.md](../../DEPLOYMENT.md) - Overall deployment documentation
- **CLI Reference**: [../../CLI_REFERENCE.md](../../CLI_REFERENCE.md) - Complete command reference
- **Architecture**: [../../ARCHITECTURE.md](../../ARCHITECTURE.md) - Technical architecture documentation

---

---

**Last Updated**: 2025-01-03
**Version**: 1.0.0
**Compatibility**: Claude Code with Bedrock v1.0+
