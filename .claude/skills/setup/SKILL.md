---
name: setup
description: "Set up the development environment for this project. Use when a user is getting started, mentions environment setup, dependency installation, or is having environment issues like missing packages or wrong Python version."
user-invocable: true
---

# Development Environment Setup

Guide the user through setting up their development environment for this project. Run each step and report results clearly.

## Steps

1. **Check Python version** — requires Python >=3.10, <3.13:
   ```bash
   python3 --version
   ```

2. **Check Poetry** — install if missing:
   ```bash
   poetry --version
   ```
   If missing, tell the user: `pip install poetry` or `pipx install poetry`

3. **Install dependencies** from the `source/` directory:
   ```bash
   cd source && poetry install
   ```

4. **Install pre-commit hooks**:
   ```bash
   cd source && poetry run pre-commit install
   ```

5. **Verify cfn-lint** is available:
   ```bash
   cd source && poetry run cfn-lint --version
   ```

6. **Run smoke tests** to confirm everything works:
   ```bash
   cd source && poetry run pytest tests/test_smoke.py -v
   ```

7. **Check AWS CLI** (optional, needed for deployment):
   ```bash
   aws --version
   ```

## Output Format

After each step, report:
- Whether it succeeded or failed
- If failed, provide the exact fix command
- At the end, summarize: what's ready, what needs attention

If everything passes, tell the user they're ready to go and suggest they try `/validate` next.
