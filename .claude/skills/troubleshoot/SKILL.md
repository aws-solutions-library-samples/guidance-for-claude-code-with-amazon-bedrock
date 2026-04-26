---
name: troubleshoot
description: "Diagnose common issues with development environment, authentication, deployment, or tests. Use when something is broken, the user is stuck, getting errors, or needs help figuring out why something isn't working."
user-invocable: true
argument-hint: "[area: env|auth|deploy|tests]"
---

# Troubleshooter

Diagnose and help fix common issues. Area: $ARGUMENTS

If no area specified, run a quick health check across all areas.

## Health Check (no arguments)

Run these checks and report status:

1. **Environment**: Python version, poetry installed, dependencies installed
2. **Config**: `~/.ccwb/config.json` exists, active profile set
3. **Tests**: smoke tests pass
4. **Templates**: cfn-lint on all templates

## Area: `env`
- Check Python version (>=3.10, <3.13)
- Check poetry installation and version
- Run `cd source && poetry install --dry-run` to check dependency state
- Check pre-commit hooks installed: `cd source && poetry run pre-commit --version`
- Check ruff, cfn-lint availability

## Area: `auth`
- Check if `~/.ccwb/config.json` exists and read active profile
- Verify provider settings (domain, client ID)
- Check if credential-process executable exists in expected location
- Suggest: `poetry run ccwb test` for live auth testing
- Common fix: `~/claude-code-with-bedrock/credential-process --clear-cache`

## Area: `deploy`
- Run `cd source && poetry run ccwb status` to check stack states
- Look for ROLLBACK_COMPLETE or FAILED stacks
- Read CloudFormation error outputs if available
- Check AWS credentials: `aws sts get-caller-identity`
- Verify Bedrock is activated in the configured region

## Area: `tests`
- Run `cd source && poetry run pytest tests/test_smoke.py -v` first
- If smoke passes, run full suite: `cd source && poetry run pytest -v --tb=short`
- For failures: read the test, read the source, explain the mismatch
- Check if running from wrong directory (must be `source/`)
- Check `conftest.py` region fixture

## Output Format

Present as a diagnostic report with clear pass/fail/fix information.
