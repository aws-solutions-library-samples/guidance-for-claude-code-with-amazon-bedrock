---
description: When modifying package.py, verify all build paths remain wired
---
- When editing `package.py`, verify that ALL platform builds (auth binary, otel-helper, otelcol) remain called from `handle()`
- Deletions in one code path (e.g., Go migration) must not remove call sites for orthogonal paths (e.g., collector sidecar)
- The sidecar path requires: `_build_otelcol()`, `_generate_collector_config()`, and either `_build_go_binaries()` or `_build_executable()`
- IDC zero-binary mode intentionally skips binary builds — don't add them
- If removing a method, search for ALL callers first — not just the one you're refactoring
