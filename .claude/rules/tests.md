---
paths:
  - "source/tests/**/*.py"
---

# Testing Rules

## Execution
- Always run from `source/` directory: `cd source && poetry run pytest`
- Smoke tests: `poetry run pytest tests/test_smoke.py` (fast, pre-commit)
- Specific file: `poetry run pytest tests/test_models.py -v`
- With coverage: `poetry run pytest --cov=claude_code_with_bedrock --cov-report=term-missing`

## Test Organization
- `tests/cli/commands/`: CLI command tests (init, deploy, package)
- `tests/test_*.py`: Core functionality (models, config, CloudFormation)
- `tests/conftest.py`: Shared fixtures — sets `AWS_DEFAULT_REGION=us-east-1`

## Mock Patterns
- AWS services: `@patch("boto3.client")` — mock at the boto3 level
- File system: use pytest `tmp_path` fixture for isolation
- Interactive prompts: mock `questionary` responses
- CloudFormation outputs: mock stack lookups with expected output keys
- Never call real AWS APIs in tests

## Common Pitfalls
- Lambda tests have module isolation issues — run them by file, not as a batch
- CloudFormation validation tests require templates to exist in `deployment/infrastructure/`
- `conftest.py` auto-sets region — don't rely on `AWS_DEFAULT_REGION` being pre-set
