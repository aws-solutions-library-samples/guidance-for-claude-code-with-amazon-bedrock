# Troubleshooting

## Step 1: Run `ccwb doctor`

```bash
poetry run ccwb doctor           # Quick health check
poetry run ccwb doctor --verbose # Detailed config dump for support
poetry run ccwb doctor --json    # Machine-readable output
```

If checks fail, the command prints a pre-filled GitHub issue URL — just click and submit.

## Debug Logging

For credential-process issues, enable debug output:

```bash
# Claude Code debug logs
CLAUDE_CODE_DEBUG_LOGS_DIR=~/.claude/debug claude --debug

# Direct credential-process test
~/claude-code-with-bedrock/credential-process --profile ClaudeCode --debug
```

## Filing a Bug

Run `ccwb doctor` — on failure it generates a pre-filled GitHub issue URL with:
- All check results
- OS, Python, auth type, monitoring mode (auto-detected)

Click the link, add any extra context, submit. That's it.

## Getting Help

- [CLI Reference](CLI_REFERENCE.md) — full command documentation
- [GitHub Issues](https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock/issues) — search existing issues
- [Monitoring Guide](MONITORING.md) — telemetry setup and dashboards
