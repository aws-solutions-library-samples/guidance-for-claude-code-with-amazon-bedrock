# CLAUDE.md — Go Command Entrypoints

## Structure

```
cmd/
├── credential-process/main.go   — AWS credential helper (called by AWS SDK)
├── otel-helper/main.go          — OTEL proxy + header injection
└── azure-assertion-smoke/       — Azure OIDC assertion test utility
```

## Adding a New Flag

1. Define with `flag.String()`/`flag.Bool()` in `main()` — group with related flags.
2. Add handling **after** `flag.Parse()` in the appropriate early-exit section.
3. Short flags: only `-p` (profile) and `-v` (version) have short forms. Be conservative.
4. Update `--explain` output if the flag affects resolved configuration.
5. Add to Python `tests/test_explain_contract.py` if it changes JSON output.

## Adding a New Subcommand

This binary uses **flags, not subcommands** (it's a credential-process, not a CLI toolkit).
New functionality should be a new `--flag`, not a positional subcommand.
Exception: if it's a wholly separate binary, create a new directory under `cmd/`.

## Entrypoint Patterns

### credential-process/main.go
- Early exits: `--version`, `--explain`, `--check-expiration`, `--clear-cache` — no auth, no network.
- Main path: read config → resolve tokens → STS federation → quota check → emit credentials.
- **Exit codes matter:** non-zero = AWS SDK retries or fails. Only exit non-zero for real failures.
- Stderr for debug output (`debugPrint`), stdout for credential JSON only.

### otel-helper/main.go
- `--status`: JSON health check (no side effects).
- Main path: start local proxy, inject OTEL headers, forward to collector.
- Must handle graceful shutdown (SIGINT/SIGTERM).

## Key Constraints
- No interactive prompts except `--login` (which is explicitly user-initiated).
- Credential output format: AWS credential-process spec (Version 1 JSON on stdout).
- Never log tokens or credentials to stderr (even in debug mode).
- Profile resolution: `--profile` flag → `CCWB_PROFILE` env → default "ClaudeCode".
