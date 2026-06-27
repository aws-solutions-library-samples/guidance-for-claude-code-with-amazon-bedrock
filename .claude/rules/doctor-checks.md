# Doctor Checks Rule

When adding new install artifacts (binaries, config files, settings):

1. Add a health check in `source/claude_code_with_bedrock/cli/commands/doctor.py`
2. Add a test in `source/tests/cli/commands/test_doctor.py`
3. Update `assets/docs/CLI_REFERENCE.md` doctor section

When adding new flags to credential-process or otel-helper:

1. Update `--explain` or `--status` output if the flag affects resolved config
2. Update `explain_test.go` with the new field assertion
3. If the flag is user-facing, add it to `credential-process --help` description

The diagnostic flags are:
- `credential-process --explain` → resolved config JSON (auth mode, provider, quota, storage, paths)
- `otel-helper --status` → proxy health + cached headers
- `ccwb doctor` → calls both + static file checks
