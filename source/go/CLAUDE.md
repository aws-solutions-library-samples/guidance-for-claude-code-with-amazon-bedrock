# CLAUDE.md — Go Binaries (credential-process + otel-helper)

## Quick Commands

```bash
cd source/go
go build ./cmd/credential-process    # Build credential-process
go build ./cmd/otel-helper           # Build otel-helper
go test ./... -race -count=1         # Run all tests (race detector on)
go vet ./...                         # Static analysis
```

## Key Rules

### Build & Version Injection
- Production builds use `_go_ldflags()` from `package.py` — injects git version + commit.
- Without ldflags, binary reports version "dev" — this is expected for local builds.
- Cross-compile targets: `linux-x64`, `linux-arm64`, `darwin-x64`, `darwin-arm64`, `windows-x64`.

### --explain Contract
- `credential-process --explain` outputs JSON describing resolved config (no auth, no network).
- Schema is validated by Python tests: `tests/test_explain_contract.py`.
- New fields: add to `ExplainOutput` struct with `json:"field_name,omitempty"`.
- **Never** make `--explain` perform auth or network calls — it's a diagnostic tool.

### --status Contract (otel-helper)
- `otel-helper --status` outputs proxy health + cached headers as JSON.
- Same rules as `--explain`: no side effects, no network, fast exit.

### Config Parity
- `internal/config/config.go` must mirror `claude_code_with_bedrock/config.py`.
- See `.claude/rules/credential-helper-parity.md` and `.claude/rules/config-sync.md`.
- When Python adds a field, Go must add it too (and vice versa).

### Windows
- **Always** use `filepath.Join` (OS-aware) — never `path.Join` (POSIX only).
- Binary resolution: check `.exe`, then `.cmd`, then `.ps1` (fallback chain).
- Test with `GOOS=windows GOARCH=amd64 go build` to catch compile errors.
- See `.claude/rules/windows-platform-guards.md`.

### Token Handling
- Single `provider.TokenEndpointURL()` builder — see `.claude/rules/token-endpoint-single-builder.md`.
- Never construct token URLs inline; always go through the centralized builder.
- Credential recursion: never invoke self — see `.claude/rules/credential-recursion.md`.

## Common Pitfalls
- Don't log secrets or tokens (even at debug level).
- Don't use `os.Exit()` in library code — return errors, let `main()` exit.
- Don't assume `HOME` exists — use `os.UserHomeDir()` with fallback.
- Don't hardcode `arn:aws:` — always read partition from config/environment.
