---
name: test
description: "Run tests with coverage and explain failures in plain English. Use when the user wants to run tests, check coverage, investigate test failures, or verify their changes work. Also use after code modifications to validate nothing is broken."
user-invocable: true
argument-hint: "[test-path-or-keyword]"
---

# Test Runner

Run tests and provide clear explanations of results, especially failures. Arguments: $ARGUMENTS

## Determine What to Run

- No arguments: run full test suite
- File path (e.g., `tests/test_models.py`): run that file
- Keyword (e.g., `models`, `init`, `config`): find matching test files and run them
- `--coverage` or `coverage`: run with coverage report

## Execution

Always run from the `source/` directory:

```bash
# Full suite
cd source && poetry run pytest -v

# Specific file
cd source && poetry run pytest tests/<file>.py -v

# With coverage
cd source && poetry run pytest --cov=claude_code_with_bedrock --cov-report=term-missing -v

# By keyword match
cd source && poetry run pytest -k "<keyword>" -v
```

## On Failure

When tests fail:
1. Read the full error output carefully
2. Identify the failing test and the assertion that failed
3. Read the test source code to understand what it expects
4. Read the source code being tested
5. Explain in plain English:
   - What the test checks
   - Why it failed
   - What needs to change (in the test OR the source code)
6. Ask the user if they want you to fix it

## Known Issues
- Lambda tests have module isolation — run by individual file if they fail as a batch
- Always run from `source/` directory (conftest.py sets AWS region)
