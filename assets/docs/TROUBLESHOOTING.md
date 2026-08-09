# Troubleshooting

## Step 1: Run `ccwb doctor`

```bash
poetry run ccwb doctor           # Quick health check
poetry run ccwb doctor --verbose # Detailed config dump
poetry run ccwb doctor --json    # Machine-readable output
```

If checks fail, the command prints a pre-filled GitHub issue URL — just click and submit.

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| CloudWatch metrics stuck at 0 | otel-helper not installed or not spawning | Re-run `ccwb package` with Go installed, then re-install |
| "Cloud authentication" error in Claude Code | Credential refresh expired (IDC) or browser auth failed (OIDC) | Run `credential-process --profile <name>` manually to re-authenticate |
| Telemetry never reaches dashboard | `otel_collector_endpoint` missing from config | Run `ccwb deploy --stack monitoring` then re-package |
| `ccwb package` reports "no binaries built" | Go not installed or wrong version | Install Go 1.24+ and re-run |
| Windows Defender blocks binaries | Unsigned Go executables trigger heuristic detection | Add install directory to exclusions (see [#649](https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock/issues/649)) |
| Region mismatch deployment failure | `aws_region` differs from Cognito/IdP region | Re-run `ccwb init` and verify region selection |

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
