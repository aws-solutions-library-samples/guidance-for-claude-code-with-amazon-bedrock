# Self-Service Portal (IAM Identity Center)

Self-service landing page for distributing Claude Desktop/Claude Code configurations with Amazon Bedrock, authenticated via IAM Identity Center (IDC). An optional admin console lets you manage per-group model access, enterprise policies, and MCP server configuration without redeploying or re-issuing installers.

This is a `distribution_type: landing-page` deployment with `auth_type: idc` of the same `landing-page-distribution.yaml` CloudFormation template used for the other landing-page IdP types (Okta/Azure/Auth0/Cognito/generic), deployed with `AuthType=idc` — it is **not** a separate stack or a separate deployment tool. The optional admin console (`ccwb deploy admin-console`) is a second, independent CloudFormation stack that attaches a `/admin*` listener rule to the same Application Load Balancer.

## Features

- **Self-Service Portal** — users download configs for their platform (macOS, Windows, JSON)
- **Admin Console** *(optional stack)* — configure models, policies, and MCP servers per group
- **IAM Identity Center Integration** — SSO authentication with group-based access control, via a Cognito User Pool that bridges SAML (IDC) to OIDC (the ALB's native `authenticate-oidc` listener action)
- **Enterprise Policy Controls** — tool restrictions (disable tools, per-tool ask/allow/block), command-level permission rules (allow/ask/deny for patterns like `Bash(git push:*)`), workspace limits, and network egress rules
- **MCP Server Management** — pre-configure remote and local MCP servers for users
- **Dynamic Config Updates** — changes propagate automatically via OIDC bootstrap (Claude Desktop polls every 30 minutes)
- **CloudFormation only** — deployed via `ccwb deploy distribution` / `ccwb deploy admin-console`, same as every other distribution type. No CDK toolchain, no `cdk bootstrap`.

## Architecture

```
User Browser ──HTTPS──> ALB (authenticate-oidc) ──> Lambda (landing page)  ──> S3 (packages/configs)
                              │
                              └─ /admin* listener rule ──> Lambda (admin console) ──> IAM Identity Center (SSO Admin + Identity Store APIs)
                                                                                  └─> Bedrock (model discovery)

Claude Desktop ──OIDC (bootstrapOidc)──> Cognito (SAML-federated w/ IDC) ──JWT──> Lambda (/api/bootstrap) ──> S3 (per-group bootstrap.json)
```

Both listener rules share:
- The same ALB (internal or internet-facing, see `ALBScheme`)
- The same Cognito User Pool (`IdcUserPool`), which SAML-federates with IAM Identity Center
- The same S3 bucket for package downloads and generated MDM/bootstrap config files

The admin console is a **separate, optional** CloudFormation stack (`admin-console.yaml`) so deployments that only need self-service downloads (no group/model/policy management UI) don't need to grant the broader IAM Identity Center + Bedrock permissions the admin console's Lambda role requires.

## Prerequisites

- **IAM Identity Center enabled** in your AWS account
- **Groups for Claude Desktop/Code users** — typically synced from your identity provider (Active Directory, Okta, Azure AD). Groups should include `Claude` in the name for the admin console to filter them (e.g. `Claude-Code-Developers`, `Claude-Code-Contractors`)
- **Admin group** — for administrators who manage the console. Must contain both `Claude` and `Admin` in the name (e.g. `Claude-Code-Admins`, the default)
- **Permission to add applications in IAM Identity Center** — after deploying the distribution stack, you'll need permission to create a **Custom SAML 2.0 application** under IAM Identity Center → Applications. This is a manual, one-time step (see Step 2 below) — IDC has no API to create custom SAML applications, and the ACS URL/Audience depend on the Cognito User Pool this stack creates, so it can't be done before deployment.
- A custom domain + ACM certificate reachable by your users. For test/internal deployments, `ALBScheme=internal` (the default for the IDC landing page) plus [SSM port forwarding](#testing-via-ssm-port-forwarding) lets you validate the setup without exposing the ALB to the internet.

## Deployment

### Step 1: Deploy the distribution stack

```bash
poetry run ccwb init
# auth_type: idc (IAM Identity Center)
# distribution: enabled, method "Authenticated Landing Page" (becomes the IDC portal because auth_type is idc)
# provide (or accept auto-detected) IAM Identity Center instance ARN
# provide admin group name (default: Claude-Code-Admins)
# provide ALB scheme: internal (default, for SSM-tunnel testing) or internet-facing

poetry run ccwb deploy distribution
```

This deploys `landing-page-distribution.yaml` with `AuthType=idc`, creating:
- `IdcUserPool` / `IdcUserPoolDomain` / `IdcUserPoolClient` — the Cognito SAML↔OIDC bridge
- The ALB, HTTPS listener, target group, and landing-page Lambda (same resources every landing-page type shares)

On completion it prints the SAML **ACS URL** and **Audience** you need for Step 2.

### Step 2: Create the SAML application in IAM Identity Center (manual)

IAM Identity Center has no API to create custom SAML applications, so this step is done once, by hand, in the AWS console:

1. **IAM Identity Center** → **Applications** → **Add application** → **Add custom SAML 2.0 application**
2. Configure:
   - **Display name:** `Claude Code Landing Page`
   - **ACS URL:** value of the `IdcSamlAcsUrl` output from Step 1
   - **Audience:** value of the `IdcSamlAudienceUri` output from Step 1
3. **Attribute mappings:**

   | Application attribute | Maps to |
   |---|---|
   | `Subject` | `${user:email}` (Format: emailAddress) |
   | `email` | `${user:email}` |

4. **Assign groups** to the application (developers, admins, etc.)
5. Copy the **SAML metadata URL**

### Step 3: Wire the SAML provider into Cognito

```bash
poetry run ccwb configure-saml <metadata-url-from-step-2>
```

This saves the metadata URL to your profile and re-deploys the distribution stack, letting CloudFormation's conditional `IdcSamlIdentityProvider` resource (and its callback-updater custom resource) create the SAML identity provider and enable it on the Cognito app client — no manual Cognito console steps required.

### Step 4 (optional): Deploy the admin console

```bash
poetry run ccwb deploy admin-console
```

Requires the distribution stack (Step 1) to already exist. This deploys `admin-console.yaml`, which:
- Attaches a `/admin*` listener rule to the distribution stack's existing ALB listener (reusing its Cognito app client — no second Cognito client, no second ALB)
- Deploys a Lambda behind that rule with IAM permissions scoped to S3 (`admin/` and `config/` prefixes only), IAM Identity Center (SSO Admin + Identity Store APIs), and Bedrock model discovery

On completion it prints the admin console URL (`https://<your-domain>/admin`). Access requires membership in the IAM Identity Center admin group configured in Step 1.

## Using the Admin Console

Once deployed, sign in to `/admin` (as a member of the admin group) to:

- View available IAM Identity Center groups (filtered to those containing `Claude`) and Bedrock models
- Edit group → model → permission-set mappings, plus policy/MCP settings, as a single JSON config
- **Save** — persists the config to S3 (`admin/config.json`) without provisioning anything
- **Deploy** — for each group mapping: creates/updates an IAM Identity Center permission set scoped to the selected Bedrock models, assigns it to the group, provisions it, and regenerates that group's `default.json` / `bootstrap.json` / `.mobileconfig` / `.reg` files in S3

Deploy is best-effort per group — one group's provisioning failure doesn't roll back others; results are reported per group.

### Tool and command controls

The **Policies** page offers two complementary layers for restricting what Claude can do. Both are delivered dynamically via bootstrap (no reinstall), and both are applied to every group's config on Deploy.

- **Tool Restrictions** — operate at the whole built-in tool level:
  - *Disabled Tools* (`disabledBuiltinTools`): remove a tool entirely (e.g. `Bash`, `NotebookEdit`). Pick from the suggested built-ins or type any tool name.
  - *Tool Policies* (`builtinToolPolicy`): set a whole tool to `allow` / `ask` / `blocked`.
- **Command Permissions** — fine-grained, command-level rules (`permissions`), the standard Claude Code allow/ask/deny model. Each rule is either a bare tool name (`WebFetch`) or a scoped pattern (`Bash(git push:*)`, `Read(./.env)`). Rules are evaluated **deny → ask → allow**, first match wins. Use this layer for command-specific gating such as "prompt before `git push`" — `builtinToolPolicy` only understands whole tool names, not shell commands, so a value like `git` there has no effect on the client.

Rules that reference a tool your provider doesn't support are ignored by the client (for example, `WebSearch` is dropped automatically on Amazon Bedrock).

### Dynamic configuration updates

MDM profiles generated by the admin console include a `bootstrapOidc` block. Claude Desktop uses it to authenticate via the same Cognito bridge and poll `/api/bootstrap` roughly every 30 minutes, picking up any config, policy, or model changes automatically — no re-distribution or reinstall needed. This is the capability that motivated adding IDC support in the first place: without it, every admin-side policy or model change would otherwise require re-pushing installers to every machine.

## Testing via SSM Port Forwarding

With `ALBScheme=internal` (the default for the IDC landing page), the ALB has no public IP and is only reachable from within the VPC. To test from your workstation without exposing it to the internet, use an EC2 instance with the SSM agent (any small instance in the same VPC, e.g. an existing bastion or a throwaway `t3.micro`) as a tunnel:

```bash
aws ssm start-session \
  --target <instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<alb-dns-name-or-custom-domain>"],"portNumber":["443"],"localPortNumber":["8443"]}'
```

Then browse to `https://localhost:8443` (accept the certificate warning if using the ALB's default DNS name rather than your custom domain — the OIDC redirect URIs are still bound to `CustomDomainName`, so for a fully working end-to-end test you'll want `/etc/hosts` pointing your custom domain at `127.0.0.1` while the tunnel is open, or test against a custom domain that already resolves privately via Route53 Resolver / VPN).

The instance needs the `AmazonSSMManagedInstanceCore` managed policy and network access to the ALB's security group (port 443).

## Troubleshooting

**"Access Denied" on admin page** — the signed-in user's IAM Identity Center groups don't include the configured admin group (default `Claude-Code-Admins`). Group membership is checked live on every request, not cached.

**Groups not showing in the admin console** — groups must contain `Claude` in the display name to appear in the group list.

**Bootstrap OIDC redirect mismatch** — the Cognito app client's callback URLs are managed automatically by the distribution stack's callback-updater custom resource; if bootstrap auth fails, re-run `ccwb deploy distribution` to refresh them.

**Config changes not appearing on Claude Desktop** — it polls every 30 minutes; restart the app to force an immediate fetch.

**Permission denied invoking Bedrock** — check the group's permission set in the admin console (`/admin/api/permission-sets`); confirm the model ARN matches an active inference profile.

**"SAML not yet configured" on the distribution stack outputs** — Step 2/3 above haven't been completed yet, or `ccwb configure-saml` failed; re-run it with a valid metadata URL.

## Cleanup

```bash
poetry run ccwb destroy admin-console  # if deployed
poetry run ccwb destroy distribution
```

Destroying does not remove IAM Identity Center groups, permission sets, or group-to-application assignments created via the admin console — remove those manually in the IAM Identity Center console if needed.
