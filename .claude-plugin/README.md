# Claude Code Plugin Marketplace Manifest

This directory contains the `marketplace.json` file that registers available plugins for discovery via Claude Code's plugin system.

## Usage

```bash
/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock
```

## What this is

The `marketplace.json` file is an index of all plugins in this repository. It tells Claude Code where to find each plugin's source directory and metadata. Individual plugins live under [`assets/claude-code-plugins/plugins/`](assets/claude-code-plugins/plugins/).

## Important

These are **example plugins** — reference implementations demonstrating enterprise development patterns. Fork and customize for your organization before production deployment.

For distribution guidance (Claude Code vs Cowork 3P), see [Plugin Distribution Guide](assets/docs/PLUGINS.md).

For the companion hands-on workshop, see [Claude Code on Amazon Bedrock Workshop](https://catalog.workshops.aws/claude-code-on-amazon-bedrock/en-US).
