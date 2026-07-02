# CLAUDE.md — Python CLI (`ccwb`) + Tests

## Quick Commands

```bash
cd source
ruff check .                    # Lint (must pass before push)
ruff format .                   # Format (must pass before push)
poetry run pytest tests/ -q     # Run all tests
poetry run pytest tests/cli/ -q # Run only CLI tests
```

## Key Rules

### Config Changes
- Add new fields to `claude_code_with_bedrock/config.py` dataclass with a **default value** (backwards compat).
- Mirror the field in `go/internal/config/config.go` — see `.claude/rules/config-sync.md`.
- Add to `--explain` output if user-visible — update `tests/test_explain_contract.py`.

### CLI Commands
- All commands live in `claude_code_with_bedrock/cli/commands/`.
- Register new commands in `__init__.py`.
- Interactive prompts: **always** guard with `sys.stdin.isatty()` check — CI and `--non-interactive` must work.
- New commands need tests in `tests/cli/commands/test_<name>.py`.

### Auth Coverage
- Any code touching identity/credentials must handle all three auth modes:
  - **OIDC** (JWT Bearer), **IDC** (IAM/SigV4), **none** (anonymous/hashed principal)
- Test the matrix. See `.claude/rules/auth-type-compat.md`.

### Testing Patterns
- Tests mirror source structure: `tests/cli/commands/`, `tests/`, etc.
- Regression tests required for bug fixes (fail without fix, pass with it).
- Use `dataclasses.replace()` to derive test profiles from `PROFILE_MODES`.
- Windows tests are **blocking** — test `pathlib.Path` and `os.sep` handling.

### Package ↔ Distribute Contract
- Binary names in `package.py` must exist in `distribute.py`'s allowlist.
- Platform normalization: generic tokens (`linux`) → qualified (`linux-x64`) early.
- See `.claude/rules/distribution-manifest-parity.md`.

## Common Pitfalls
- Don't use `rm -rf` in tests — use `tmp_path` fixtures.
- Don't hardcode `/` as path separator — use `pathlib.Path`.
- Don't call `questionary.select()` without `_is_interactive()` guard.
- Don't add optional imports without try/except and feature-gate.
