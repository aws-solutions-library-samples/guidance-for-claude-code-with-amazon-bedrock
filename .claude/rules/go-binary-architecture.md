# Go Binary Architecture

## Rule
Understand the Go module layout and build constraints before modifying credential-process or otel-helper.

## Module Structure

```
source/go/
├── cmd/
│   ├── credential-process/   # Main binary — auth, quota, OTEL attribution
│   │   ├── main.go           # OIDC flow, entry point, CLI flags
│   │   ├── idc.go            # IDC active SSO flow (device auth)
│   │   ├── passthrough.go    # IDC passthrough (ambient creds)
│   │   ├── proxy.go          # Auto-spawn otel-helper proxy for CoWork identity
│   │   ├── proxy_unix.go     # Unix process detach (setsid)
│   │   └── proxy_windows.go  # Windows no-op detach
│   └── otel-helper/          # OTEL header generation + signing proxy
│       ├── main.go           # Header extraction from JWT
│       └── proxy.go          # SigV4 signing proxy + identity injection for CoWork
├── internal/
│   ├── browser/              # OS-specific browser open
│   ├── config/               # ProfileConfig struct (mirrors Python Profile)
│   ├── federation/           # STS + Cognito identity federation
│   ├── jwt/                  # JWT decode (no verification — claims only)
│   ├── oidc/                 # OIDC PKCE flow, callback server, token exchange
│   ├── otel/                 # OTEL cache, header extraction, user info
│   ├── portlock/             # Exclusive port lock (prevent parallel auth)
│   ├── provider/             # OIDC provider detection (Okta, Azure, etc.)
│   ├── quota/                # Quota check (Bearer for OIDC, SigV4 for IDC)
│   ├── storage/              # Keyring, refresh tokens, session cache, quota state
│   └── version/              # Build version injection via ldflags
└── Makefile                  # Cross-compilation targets
```

## Build Rules

- **credential-process:** `CGO_ENABLED=1` on macOS (keyring requires cgo), `CGO_ENABLED=0` elsewhere
- **otel-helper:** Always `CGO_ENABLED=0` (no keyring dependency)
- **Windows:** Do NOT strip symbols (`-s -w`) — Defender flags stripped Go binaries
- **Version:** Injected via `-ldflags -X ccwb-go/internal/version.Version=...`
- **Binary naming:** `{cmd}-{os}-{arch}` (e.g., `credential-process-macos-arm64`)

## Critical Constraints

- **stdout is sacred** in credential-process: only the final JSON credential output. All other output → stderr.
- **No AWS SDK usage** for credential resolution inside credential-process (infinite recursion). Direct HTTPS only for token exchange.
- **Port lock** prevents parallel auth flows — hold exclusive port during browser auth.
- **Performance:** Cache hot path must be <20ms. Go binary cold start target <100ms.

## IDC Modes

| Mode | File | When |
|------|------|------|
| **Active SSO** | `idc.go` | `auth_type=idc` + IDC config present. Drives SSO OIDC device-auth. |
| **Passthrough** | `passthrough.go` | `auth_type=idc` + no IDC config. Uses ambient `aws sso login` creds. |

## Testing

- `cd source/go && go test ./... -v`
- Tests must not require real AWS credentials or network
- Use `t.Setenv()` for environment variable mocking
- Platform-specific behaviour uses `runtime.GOOS` guards

## Adding New Features

1. Add to appropriate `internal/` package (keep `cmd/` thin)
2. Mirror any config fields in Python `Profile` dataclass (see `config-sync.md`)
3. Add tests in the same package (Go convention: `foo_test.go`)
4. Ensure cross-platform: test file paths, encoding, permissions on all OS
5. Update Makefile if adding a new binary target

## Related Rules
- `credential-helper-parity.md` — Go and Python must produce identical outputs
- `credential-flow.md` — Runtime flow diagram
- `credential-recursion.md` — Never use AWS SDK for cred resolution
- `config-sync.md` — Go struct ↔ Python dataclass sync
- `binary-distribution.md` — Platform signing and startup time
- `windows-platform-guards.md` — Windows-specific concerns
