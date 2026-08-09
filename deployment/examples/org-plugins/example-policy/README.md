# Example Organization Plugin

This directory demonstrates the structure of an organization plugin that can be
served by the bootstrap device-code server's `/plugins` endpoint.

## What it shows

- **`.claude-plugin/plugin.json`** — Plugin manifest with name, version, and
  installation preference (`required` means all users in the org get it).
- **`skills/code-review/SKILL.md`** — An organization-wide skill that enforces
  a code review checklist across all Claude Code sessions.

## Usage

Host this directory (or a zip of it) at a URL and reference it in the plugin
registry JSON served by your bootstrap server:

```json
{
  "plugins": [
    {
      "name": "example-org-policy",
      "version": "1.0.0",
      "url": "https://your-api.example.com/plugins/example-org-policy.zip"
    }
  ]
}
```

Claude Desktop will fetch and install organization plugins automatically during
the bootstrap handshake.
