---
name: validate
description: "Run the full validation suite: linting, formatting, CloudFormation validation, and smoke tests. Use whenever the user wants to check if everything is working, verify code quality, or run all checks before committing."
user-invocable: true
argument-hint: "[--fix]"
---

# Full Validation Suite

Run all validation checks for the project. Report results as a clear checklist.

If the user passes `--fix`, auto-fix what's possible. Arguments: $ARGUMENTS

## Checks to Run (in order)

1. **Python linting** (ruff check):
   ```bash
   cd source && poetry run ruff check . $( [ "$1" = "--fix" ] && echo "--fix" || echo "" )
   ```

2. **Python formatting** (ruff format):
   ```bash
   cd source && poetry run ruff format --check .
   ```
   If `--fix` was passed: `cd source && poetry run ruff format .`

3. **CloudFormation validation** (cfn-lint):
   ```bash
   cd source && poetry run cfn-lint ../deployment/infrastructure/*.yaml
   ```

4. **YAML lint**:
   ```bash
   cd source && poetry run yamllint ../deployment/infrastructure/
   ```

5. **Smoke tests**:
   ```bash
   cd source && poetry run pytest tests/test_smoke.py -v
   ```

## Output Format

Present results as a checklist:
```
Validation Results:
  [PASS] Python linting — no issues
  [PASS] Python formatting — all files formatted
  [WARN] CloudFormation — 2 warnings in otel-collector.yaml (non-blocking)
  [PASS] Smoke tests — 5/5 passed
```

If there are failures, explain what's wrong and how to fix it.
