# Web Search for Claude Code (Amazon Bedrock AgentCore)

This guide explains how to give Claude Code a hosted **web-search tool** through an
[Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/) gateway, using
the same OIDC identity your deployment already mints. No local proxy and no new developer
prerequisite — Claude Code connects to the gateway natively as a remote MCP server.

## Overview

When web search is enabled, `ccwb deploy` provisions an AgentCore **Gateway** (an MCP
server) with a managed **web-search** connector target. The gateway's authorizer is
`CUSTOM_JWT`: it validates the **same id_token** your identity provider issues for Bedrock
access, so any user who can already authenticate can use web search — no extra IAM grant.

`ccwb package` then writes an `mcpServers.agentcore-websearch` block into the generated
`settings.json`. Claude Code connects to the gateway over HTTPS and attaches the Bearer
JWT per request via the credential helper's `--get-mcp-auth-header` mode.

```
OIDC id_token  ──▶  AgentCore Gateway (CUSTOM_JWT, us-east-1)  ──▶  web-search connector
   (minted by your IdP)        validates the token               returns cited results
```

> **Availability:** This is the path for **OIDC** deployments (an external IdP such as
> Okta, Microsoft Entra ID, Auth0, Google, or a Cognito User Pool). Non-SSO deployments
> (AWS IAM Identity Center or no-auth) have no id_token to validate and are not yet
> supported — enabling web search on those deployments is skipped at deploy time.

## Cost

Web search is **billed to your AWS account at approximately $7 per 1,000 queries** (in
addition to Bedrock model usage). There is no built-in per-user cap.

> **Recommendation:** Before rolling this out broadly, set an **[AWS Budget](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)**
> or a **[Cost Anomaly Detection](https://docs.aws.amazon.com/cost-management/latest/userguide/getting-started-ad.html)**
> alert so unexpected query volume surfaces quickly. Hard per-user capping is not part of
> this feature in v1.

## Region constraint

The AgentCore web-search connector is a managed service available in **us-east-1 only**.
`ccwb` therefore deploys the web-search gateway to **us-east-1 regardless of your
deployment's primary region** — the rest of your infrastructure stays where you configured
it. This is the one deliberate region-pin in the solution; you do not need to change your
`aws_region` to use web search.

## Acceptable use — citation retention

The web-search results include **source citations**. Per the service's acceptable-use
terms you **must retain and display these citations** to end users. Do not use the tool for
bulk content extraction or to build a competing search index. Claude Code surfaces the
citations in its responses by default; do not strip them.

## Enabling web search

### New deployment

1. Run `ccwb init`. In the **Web Search (AgentCore)** prompt, answer **yes** (the prompt
   discloses the ~$7/1,000-query cost and the us-east-1-only constraint). This is optional
   and skippable — declining leaves it off.
2. Run `ccwb deploy`. The web-search gateway deploys to us-east-1; `ccwb` waits for the
   connector target to reach **READY** and saves the gateway URL to your profile.
3. Run `ccwb package` and distribute/install the package as usual. The generated
   `settings.json` now contains the `agentcore-websearch` MCP server.

### Existing deployment (late enablement)

You can adopt web search without tearing anything down:

```bash
# 1. Re-run init and answer "yes" to the web-search prompt (other answers round-trip).
poetry run ccwb init

# 2. Deploy just the web-search stack (us-east-1).
poetry run ccwb deploy websearch

# 3. Rebuild and reinstall the package so settings.json gains the MCP server.
poetry run ccwb package
```

## Verifying it works

After installing the package, confirm Claude Code sees and connects to the gateway:

```bash
# The agentcore-websearch server should be listed and show as connected.
claude mcp list
```

Then ask Claude Code something that requires current information, for example:

> What are the AWS service announcements from this week?

A working setup returns **current results with source citations**. If the server shows as
failed or absent, see Troubleshooting below.

## Troubleshooting

- **`claude mcp list` doesn't show `agentcore-websearch`** — The block is only written when
  web search is enabled *and* a gateway URL is known. Run `ccwb deploy websearch` first,
  then re-run `ccwb package` and reinstall.
- **Server shows as failed / authentication errors** — The gateway validates your OIDC
  id_token. Make sure you have a current session (the credential helper refreshes tokens
  silently; if it can't, re-authenticate). The `--get-mcp-auth-header` mode never opens a
  browser, so an expired, unrefreshable token fails cleanly rather than hanging.
- **Deploy reports the target never reached READY** — The connector provisions
  asynchronously after the CloudFormation stack completes. Re-run `ccwb deploy websearch`
  to re-check; the error message includes the target's status reason.
- **Google: `403 insufficient_scope` despite a valid login** — Google issues the `iss`
  (issuer) claim as either `https://accounts.google.com` or the bare `accounts.google.com`,
  and the gateway matches the issuer strictly. Claude Code's normal browser sign-in uses the
  authorization-code flow, which emits the `https://` form the gateway expects, so this works
  out of the box. You'd only hit the bare-issuer form with a manually minted token (e.g.
  `gcloud auth print-identity-token` or a service-account token) — use a real interactive
  sign-in instead.

## Install caveat — preserve your own `mcpServers`

> ⚠️ **Re-running the installer overwrites `~/.claude/settings.json`.** It does **not**
> merge — any `mcpServers` (or other settings) you added yourself are replaced by the
> generated file. On **macOS/Linux** the installer first writes a timestamped backup
> (`~/.claude/settings.json.backup-<timestamp>`); on **Windows** there is **no backup**.
>
> If you maintain your own MCP servers or custom settings, **back up
> `~/.claude/settings.json` before reinstalling** and re-merge your entries afterward.

## See also

- [CLI Reference](./CLI_REFERENCE.md) — `ccwb deploy websearch`
- [Cost Estimates](./COST_ESTIMATES.md) — overall deployment cost planning
- [Quick Start](../../QUICK_START.md) — full deployment walkthrough
