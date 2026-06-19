# Plugin Distribution Guide

This guidance ships example Claude Code plugins demonstrating enterprise development patterns. These plugins work with both **Claude Code** (CLI) and **Claude Cowork** (Desktop) but are distributed differently depending on your deployment model.

> **⚠️ Important:** These are example starting points — fork and customize for your organization before production use. Adapt security policies, tooling integrations, and workflows to match your environment.

## Distribution Models

### Claude Code (developer-initiated)

Developers install plugins directly from this repository's marketplace using the Claude Code CLI:

```bash
# Add this repo as a marketplace source
/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock

# Install a specific plugin
/plugin install security@aws-claude-code-plugins

# Update all marketplace plugins
/plugin marketplace update
```

Plugins are stored in the user's local `.claude/plugins/` directory. Users choose which plugins to install and can remove them at any time.

**Official documentation:** [Discover and install plugins](https://code.claude.com/docs/en/discover-plugins) | [Create a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)

### Claude Cowork on 3P (admin-managed)

For Cowork on third-party platforms (e.g., Amazon Bedrock), administrators provision plugins through the filesystem rather than the marketplace CLI. There are three extension layers, in order of precedence:

| Layer | Provisioned by | Delivered via |
|-------|---------------|---------------|
| Managed MCP servers | Admin | `managedMcpServers` configuration key |
| Organization plugins | Admin | System-wide directory on each device |
| User extensions | End user | In-app Connectors and Plugins UI |

**Organization plugins** are distributed by placing plugin directories on each device via MDM (Jamf, Intune, Group Policy) or your standard software distribution channel. Users cannot remove admin-provisioned plugins.

**Recommended workflow for Cowork 3P:**

1. **Fork** this repository
2. **Customize** plugins for your organization (connectors, terminology, workflows, security policies)
3. **Push** the customized plugin directories to devices via MDM alongside the managed-settings configuration
4. Optionally disable the user extension layer if you want admin-only control

**Official documentation:** [MCP, plugins, skills, and hooks for Cowork 3P](https://claude.com/docs/cowork/3p/extensions)

### Comparison

| Aspect | Claude Code | Cowork 3P (admin) |
|--------|------------|-------------------|
| Install mechanism | `/plugin marketplace add` (git-backed) | MDM push to filesystem |
| Who decides | Individual developer | IT administrator |
| Removable by user | Yes | No (org plugins) |
| Update mechanism | `/plugin marketplace update` | Re-push via MDM |
| MCP servers | Bundled in plugin `.mcp.json` | Separate `managedMcpServers` config key |
| Team enforcement | `.claude/settings.json` `requiredPlugins` | MDM policy |

## Customization Before Deployment

These plugins are designed as **templates**, not turnkey solutions. Before deploying to your organization:

- **Security plugin:** Review PII patterns for your jurisdiction, adjust regex rules, configure audit log destinations
- **Architecture plugin:** Update architecture decision record (ADR) templates to match your standards
- **EPCC workflow:** Customize commit message formats, branch naming, and review processes
- **All plugins:** Update `.mcp.json` connector configurations to point at your internal tools

## Workshop

For a guided walkthrough of these plugins, see the companion workshop:
[Claude Code on Amazon Bedrock Workshop](https://catalog.workshops.aws/claude-code-on-amazon-bedrock/en-US)

## Related Resources

- [Anthropic's knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins) — Official role-based plugin examples for Cowork
- [Claude Code Plugin Reference](https://code.claude.com/docs/en/plugins) — Full plugin authoring guide
- [Cowork 3P Configuration Reference](https://claude.com/docs/cowork/3p/configuration) — Managed settings schema
- [COWORK_3P.md](COWORK_3P.md) — This guidance's Cowork 3P deployment guide
