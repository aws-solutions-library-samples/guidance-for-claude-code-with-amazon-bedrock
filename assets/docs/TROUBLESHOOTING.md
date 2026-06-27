# Troubleshooting

Debugging issues remotely is hard — we often can't reproduce problems because we don't know the user's auth type, monitoring mode, OS, or which hooks are configured. `ccwb doctor` solves this by collecting the full environment picture in one command.

## Run `ccwb doctor`

```bash
poetry run ccwb doctor           # Quick health check
poetry run ccwb doctor --verbose # Full config dump (what support needs)
poetry run ccwb doctor --json    # Machine-readable (pipe to Claude or scripts)
```

On failure, the command prints a pre-filled GitHub issue URL with auto-detected OS, auth type, monitoring mode, and all check results. Click the link and submit — no manual environment description needed.

## Debug Logging

For credential or auth issues that need deeper investigation:

```bash
# Claude Code debug logs
CLAUDE_CODE_DEBUG_LOGS_DIR=~/.claude/debug claude --debug

# Direct credential-process test
~/claude-code-with-bedrock/credential-process --profile ClaudeCode --debug
```

## Getting Help

- [CLI Reference](CLI_REFERENCE.md) — full command documentation
- [GitHub Issues](https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock/issues) — search existing issues
- [Monitoring Guide](MONITORING.md) — telemetry setup and dashboards
