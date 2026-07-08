# Distribution Platform Comparison

## Overview

Claude Code with Bedrock supports three distribution methods for sharing packaged binaries and settings with end users:

1. **Presigned S3 URLs** - Simple, no authentication required
2. **Authenticated Landing Page** - Enterprise-grade with external IdP integration (Okta/Azure/Auth0/Cognito)
3. **Self-Service Portal (IAM Identity Center)** - the same ALB + Lambda + S3 CloudFormation stack as the Landing Page, with `IdPProvider=idc` (Cognito bridges SAML/IDC to OIDC), plus an optional separate admin console stack for managing models/policies/MCP servers

This guide helps you choose the right option for your organization. For the IAM Identity Center portal specifically, see [idc-self-service-portal.md](idc-self-service-portal.md).

---

## Quick Comparison

| Feature             | Presigned S3 URLs                  | Landing Page (external OIDC)            | Self-Service Portal (IAM Identity Center) |
| ------------------- | ----------------------------------- | --------------------------------------- | ------------------------------------------ |
| **Best For**        | Small teams (< 20 users)           | Large teams (20-100 users)              | Orgs already using IAM Identity Center     |
| **Authentication**  | None (URLs shared via Slack/email) | IdP (Okta/Azure/Auth0/Cognito)          | Native IAM Identity Center SSO             |
| **Setup Time**      | 5 minutes                          | 30 minutes                              | 45-60 minutes (SAML + Cognito federation setup) |
| **Security**        | URL expiry (7 days)                | IdP auth + URL expiry (1 hour)          | Signed session cookies + JWT bootstrap auth |
| **Compliance**      | Basic                              | Enterprise-grade                        | Enterprise-grade                           |
| **User Experience** | Copy/paste URL                     | Navigate to URL, authenticate, download | Navigate to URL, SSO login, download; configs auto-update via bootstrap |
| **Admin Overhead**  | Generate new URLs when needed      | Set up once, no maintenance             | Admin console for models/policies/MCP servers, group-based access |
| **Access Control**  | Anyone with URL                    | IdP groups/users                        | IAM Identity Center groups → per-group permission sets |
| **Deployment tool** | CloudFormation (`ccwb deploy`)     | CloudFormation (`ccwb deploy`)          | CloudFormation (`ccwb deploy distribution` + optional `ccwb deploy admin-console`) |

---

## Architecture Comparison

### Presigned S3 URLs

```
Admin Machine → S3 → Presigned URL (7 days) → User downloads directly
```

**How it works:**

1. Admin runs `poetry run ccwb distribute`
2. Package uploaded to S3
3. Presigned URL generated (expires in 7 days)
4. Admin shares URL via Slack/email
5. Users download directly from S3 (no authentication)

**Pros:**

- Simple setup (no VPC, no IdP web app configuration)
- Works immediately after deployment
- No user authentication required

**Cons:**

- URL can be shared with anyone
- URLs expire after 7 days (need to regenerate)
- No audit trail of who downloaded
- Not suitable for compliance requirements

---

### Authenticated Landing Page

```
Admin Machine → S3 → Lambda (generates presigned URLs) → User authenticates via IdP → Downloads from S3
                       ↑
                      ALB (OIDC)
```

**How it works:**

1. Admin runs `poetry run ccwb distribute`
2. Package uploaded to S3
3. Admin shares landing page URL via Slack/email
4. Users navigate to landing page
5. ALB redirects to IdP for authentication
6. After authentication, Lambda generates presigned URLs
7. Users download from S3 (authenticated)

**Pros:**

- Enterprise-grade security (IdP authentication)
- Access control via IdP groups
- Professional landing page UI
- Presigned URLs expire after 1 hour (limited sharing)
- Suitable for compliance requirements
- No need to regenerate URLs (landing page always available)

**Cons:**

- More complex setup (VPC, IdP web app configuration)
- Requires IdP web application configuration
- Requires networking stack (VPC, subnets)

---

## Decision Matrix

### Use Presigned S3 URLs when:

- ✅ Team size < 20 users
- ✅ Internal/trusted users only
- ✅ No compliance requirements
- ✅ Simple setup preferred
- ✅ Users can safely share URLs
- ✅ Cost is a primary concern
- ✅ No IdP infrastructure available

### Use Landing Page when:

- ✅ Team size 20-100 users
- ✅ External or untrusted users
- ✅ Compliance requirements (SOC2, audit trails)
- ✅ Already using an external IdP (Okta/Azure/Auth0/Cognito) for other systems
- ✅ Need tight access control
- ✅ Professional UI preferred
- ✅ Want permanent distribution URL

### Use Self-Service Portal (IAM Identity Center) when:

- ✅ Your org already uses AWS IAM Identity Center for workforce SSO
- ✅ You want an admin console to manage models, policies, and MCP servers per group without redeploying
- ✅ You want Claude Desktop configs to update automatically (via bootstrap) without re-issuing installers
- ✅ You want everything deployed via CloudFormation, consistent with every other `ccwb deploy` stack (no CDK toolchain required)

---

## Setup Process Comparison

### Presigned S3 URLs Setup

1. Run `poetry run ccwb init`
2. Select "Presigned S3 URLs (simple, no authentication)"
3. Run `poetry run ccwb deploy distribution`
4. Wait 2-3 minutes for deployment
5. **Ready to use!**

### Landing Page Setup

1. Create web application in your IdP:
   - Okta: Create "Web Application"
   - Azure AD: Register application with "Web" platform
   - Auth0: Create "Regular Web Application"
   - Cognito: Create app client with "Authorization code" grant
2. Run `poetry run ccwb init`
3. Select "Authenticated Landing Page (IdP + ALB)"
4. Enter IdP details (domain, client ID, client secret)
5. Run `poetry run ccwb deploy distribution`
6. Wait 5-10 minutes for deployment
7. Configure IdP redirect URI (displayed after deployment)
8. **Ready to use!**

### Self-Service Portal (IAM Identity Center) Setup

1. Run `poetry run ccwb init`
2. Select "Self-Service Portal (IAM Identity Center)"
3. Provide (or let the wizard auto-detect) your IAM Identity Center instance ARN and admin group name
4. Run `poetry run ccwb deploy distribution` — deploys `landing-page-distribution.yaml` (`IdPProvider=idc`), the same CloudFormation template used by the other landing-page types (prints SAML ACS URL/Audience and next steps on completion)
5. Create a **Custom SAML 2.0 application** in IAM Identity Center (manual, AWS console — using the ACS URL/Audience from Step 4's output)
6. Run `poetry run ccwb configure-saml <metadata-url>` — saves the metadata URL to your profile and re-deploys the distribution stack, letting CloudFormation's conditional SAML identity-provider resource wire itself into Cognito automatically
7. Assign IAM Identity Center groups to the application
8. (Optional) Run `poetry run ccwb deploy admin-console` to deploy a separate stack that adds a `/admin` console (attached to the same ALB) for configuring models, policies, and MCP servers per group
9. **Ready to use!** Users authenticate with IAM Identity Center and download configs that self-update via bootstrap

See [idc-self-service-portal.md](idc-self-service-portal.md) for the full step-by-step deployment instructions.

---

## Security Comparison

### Presigned S3 URLs

**Security Features:**

- Presigned URL with time-based expiry (7 days max)
- S3 bucket not publicly accessible
- IAM user with read-only permissions
- Package integrity via SHA256 checksum

**Security Limitations:**

- No authentication required (anyone with URL can download)
- URLs can be shared/leaked
- No audit trail of downloads
- Need to regenerate URLs regularly

**Risk Level:** Medium (suitable for internal trusted users)

### Landing Page

**Security Features:**

- IdP authentication required (corporate credentials)
- ALB OIDC integration (OAuth 2.0 standard)
- Presigned URLs with short expiry (1 hour)
- Access control via IdP groups
- S3 bucket not publicly accessible
- CloudWatch logging for troubleshooting

**Security Limitations:**

- Presigned URLs valid for 1 hour (limited window for sharing)
- Requires users to have IdP access

**Risk Level:** Low (suitable for enterprise compliance)

### Self-Service Portal (IAM Identity Center)

**Security Features:**

- Native IAM Identity Center SSO (no separate IdP credential set) via the ALB's native `authenticate-oidc` listener action (same mechanism as the other landing-page types) — no custom session-cookie logic
- Bootstrap API validates the caller's Cognito access token via `/oauth2/userInfo` before returning config
- CSRF protection via Origin-header verification on admin POST requests
- Per-group authorization on config downloads (fail-closed group filtering)
- Admin console access requires a live IAM Identity Center group lookup on every request (never trusted from a token claim) against an admin group name
- S3 bucket not publicly accessible
- HTML output escaped to prevent XSS; error responses do not leak internal exception detail

**Security Limitations:**

- Requires users to have IAM Identity Center access
- Requires a one-time SAML federation setup between Cognito and IAM Identity Center

**Risk Level:** Low (suitable for enterprise compliance)

---

## Switching Between Types

You can switch between distribution types by:

1. Run `poetry run ccwb init` (reconfigure)
2. Select different distribution type
3. Run `poetry run ccwb deploy distribution`
4. CloudFormation will replace the stack with the new type

**Note:** All three distribution types (Presigned S3, Landing Page, and the IAM Identity Center portal) share the same `landing-page-distribution.yaml`/`presigned-s3-distribution.yaml` CloudFormation stack name, so you can't have more than one deployed simultaneously — `ccwb init` only tracks one active `distribution_type` per profile at a time. The admin console (`ccwb deploy admin-console`) is a separate stack and must be destroyed/redeployed independently if you switch away from `landing-page-idc`.

---

## Recommendations

### Start with Presigned S3 if:

- You're testing/prototyping
- Team is small and internal
- You want immediate setup
- Cost is critical

### Upgrade to Landing Page when:

- Team grows beyond 20 users
- You need compliance/audit trails
- You need access control
- You want professional UX
- You already use an external IdP (Okta/Azure/Auth0/Cognito)

### Choose the Self-Service Portal (IAM Identity Center) when:

- Your org's workforce identity is already IAM Identity Center
- You want a persistent admin console rather than redeploying to change policy
- You want Claude Desktop configs to refresh automatically without re-distributing installers

---

## FAQ

**Q: Can I have both types deployed at once?**
A: No — all three distribution types share the same CloudFormation stack name, so choose one per deployment. The admin console is a separate stack, but only makes sense alongside the IAM Identity Center portal.

**Q: How do I switch from Presigned S3 to Landing Page?**
A: Run `ccwb init` to reconfigure, then `ccwb deploy distribution` to update the stack.

**Q: Do both CloudFormation-based types work with the same `ccwb distribute` command?**
A: Yes! The publish process is identical for Presigned S3 and Landing Page. Only the download method differs. The Self-Service Portal (IAM Identity Center) manages its own config delivery via the bootstrap API rather than `ccwb distribute`.

**Q: Can users download without authentication on the landing page?**
A: No, ALB requires IdP authentication before users can access the landing page. The Self-Service Portal similarly requires IAM Identity Center SSO before any download or config fetch.

**Q: What happens if presigned URLs expire?**
A: For presigned-s3: Generate new URLs with `ccwb distribute`. For landing-page: URLs regenerate automatically when users visit.

**Q: Can I use a custom domain?**
A: Yes for all three types — Landing Page, Presigned S3 (S3 URLs directly), and the Self-Service Portal (IAM Identity Center), which uses the same `CustomDomainName`/Route53 parameters as the external-IdP Landing Page.

**Q: Does the Self-Service Portal (IAM Identity Center) require a VPC?**
A: Yes — it uses the same ALB + Lambda architecture as the external-IdP Landing Page, so it requires the networking stack (`ccwb deploy networking`) just like that option does.

---

## Next Steps

- For setup instructions, see distribution setup guides
- For publishing packages, see [Publishing Guide](publishing.md)
- For user instructions, see [User Guide](user-guide.md)
