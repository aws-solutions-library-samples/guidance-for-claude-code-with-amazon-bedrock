# credential-refresher

Background daemon that keeps `~/.aws/credentials` fresh for session-storage mode, eliminating the per-request overhead of spawning `credential-process`.

## Problem

In session-storage mode, `credential-process` is invoked on **every** Claude Code API request. Each invocation adds ~200-500ms of latency (process spawn + file I/O + cache check). Over a coding session with hundreds of requests, this compounds to minutes of cumulative delay.

## Solution

`credential-refresher` runs as a background process that:

1. Monitors credential expiry in `~/.aws/credentials`
2. Proactively refreshes before they expire (10-minute buffer)
3. Uses the same `credential-process` binary for the actual refresh

This means the AWS SDK reads credentials directly from the file (**zero subprocess overhead**) while the daemon ensures they're always valid.

## Usage

```bash
# Start daemon (background)
credential-refresher --profile ClaudeCode &

# One-shot check/refresh
credential-refresher --profile ClaudeCode --once

# Check status
credential-refresher --profile ClaudeCode --status

# Stop running daemon
credential-refresher --profile ClaudeCode --stop
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--profile` | Configuration profile name | `ClaudeCode` |
| `--interval` | Check interval in seconds | `300` (5 min) |
| `--once` | Check once and exit | - |
| `--status` | Show daemon status | - |
| `--stop` | Stop running daemon | - |

## How it works

```
┌──────────────────┐     reads directly      ┌─────────────────────┐
│   Claude Code    │ ─────────────────────── │ ~/.aws/credentials  │
│   (AWS SDK)      │    (zero overhead)       │  [ClaudeCode]       │
└──────────────────┘                          └──────────┬──────────┘
                                                         │ writes
                                              ┌──────────┴──────────┐
                                              │ credential-refresher │
                                              │  (background daemon) │
                                              └──────────┬──────────┘
                                                         │ invokes when
                                                         │ near expiry
                                              ┌──────────┴──────────┐
                                              │ credential-process   │
                                              │  (OIDC → STS)       │
                                              └─────────────────────┘
```

## Requirements

- `credential_storage` must be `"session"` in config.json
- `credential-process` binary must be in the same directory

## Security

- Credentials file: `0600` permissions, `~/.aws/credentials`
- PID file: `0600`, `~/.claude-code-session/refresher-{profile}.pid`
- Same trust model as `aws sso login` (short-lived creds in local file)
- Daemon runs unprivileged as the current user
