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

### Distribution Comparison

| Aspect | Claude Code | Cowork 3P (admin) |
|--------|------------|-------------------|
| Install mechanism | `/plugin marketplace add` (git-backed) | MDM push to filesystem |
| Who decides | Individual developer | IT administrator |
| Removable by user | Yes | No (org plugins) |
| Update mechanism | `/plugin marketplace update` | Re-push via MDM |
| MCP servers | Bundled in plugin `.mcp.json` | Bundled `.mcp.json` + separate `managedMcpServers` config key |
| Team enforcement | `.claude/settings.json` `requiredPlugins` | MDM policy |

## Plugin Component Differences

The plugin directory format is largely shared between Claude Code and Cowork, but each product supports different component types:

| Component | Claude Code | Cowork | Notes |
|-----------|:-----------:|:------:|-------|
| Skills (`skills/`) | ✅ | ✅ | Same format on both |
| Commands (`commands/`) | ✅ | ✅ | Slash commands |
| Agents/Sub-agents (`agents/`) | ✅ | ✅ | Same format on both |
| Hooks (`hooks/hooks.json`) | ✅ | ✅ | Same lifecycle events |
| MCP servers (`.mcp.json`) | ✅ | ✅ | Called "connectors" in Cowork UI |
| LSP servers | ✅ | ❌ | Code intelligence (editor-only) |
| Monitors | ✅ | ❌ | Claude Code-specific |
| Themes | ✅ | ❌ | Terminal UI theming |
| Tool policy locks | ❌ | ✅ | Admin can set `allow`/`ask`/`blocked` per tool |

**Key behavioral differences:**

- **MCP server approval:** In Claude Code, users approve MCP server access at runtime. In Cowork org plugins, MCP servers are pre-approved by the administrator — users cannot block them.
- **Connectors vs MCP servers:** Cowork uses the term "connectors" in the UI for MCP servers. The underlying protocol (MCP) is the same.
- **Standalone MCP provisioning:** Cowork admins can deploy MCP servers *without* a plugin via the `managedMcpServers` configuration key. Claude Code requires MCP servers to be either in a plugin's `.mcp.json` or in the user's `.claude/settings.json`.
- **LSP/Monitors/Themes:** These are Claude Code-specific (terminal editor features). Plugins containing only these components won't provide any value when deployed to Cowork.

**Official documentation:**
- Claude Code plugin components: [Plugins reference](https://code.claude.com/docs/en/plugins-reference)
- Cowork 3P extensions: [MCP, plugins, skills, and hooks](https://claude.com/docs/cowork/3p/extensions)

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
