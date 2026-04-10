# Tech Stack & Build

## Language & Runtime

- Python 3.10–3.12 (constrained in pyproject.toml)
- Poetry for dependency management (lockfile: `source/poetry.lock`)

## Core Dependencies

| Library | Purpose |
|---------|---------|
| boto3 | AWS SDK |
| cleo | CLI framework |
| rich | Terminal UI / progress bars |
| pydantic | Data validation & config models |
| questionary | Interactive prompts |
| PyJWT | JWT token handling |
| keyring | OS credential storage |
| cryptography | Encryption |
| requests | HTTP client |
| pyyaml | YAML parsing |
| cfn-flip | CloudFormation template conversion |

## Dev Dependencies

| Tool | Purpose |
|------|---------|
| pytest / pytest-cov | Testing (176+ tests) |
| ruff | Linting & formatting (primary) |
| black | Code formatting (line-length 120) |
| mypy | Static type checking (`disallow_untyped_defs = true`) |
| cfn-lint | CloudFormation template validation |
| yamllint | YAML validation |
| pre-commit | Git hook automation |
| pyinstaller | macOS/Linux executable builds |
| nuitka | Windows executable builds (via CodeBuild) |
| shiv | Python archive packaging |

## Code Style

- Line length: 120 (both Ruff and Black)
- Target: Python 3.10
- Ruff rules enabled: E, W, F, I (isort), B (bugbear), C4 (comprehensions), UP (pyupgrade)
- Ruff auto-fixes on pre-commit
- Type annotations required (`mypy --disallow-untyped-defs`)

## Infrastructure

- AWS CloudFormation (YAML templates in `deployment/infrastructure/`)
- Templates are validated by cfn-lint and optionally by AWS CLI
- Partition-aware: supports AWS Commercial and GovCloud

## Common Commands

All commands run from the `source/` directory:

```bash
# Setup
poetry install

# Testing
poetry run pytest                          # full test suite
poetry run pytest tests/test_smoke.py -q   # quick smoke tests

# Linting & Formatting
poetry run ruff check .                    # lint
poetry run ruff check . --fix              # lint with auto-fix
poetry run ruff format .                   # format (ruff)
poetry run black .                         # format (black)

# Type Checking
poetry run mypy .                          # static analysis

# Pre-commit (run from repo root)
pre-commit run --all-files

# CLI (deployment tool)
poetry run ccwb init                       # interactive setup wizard
poetry run ccwb deploy                     # deploy AWS infrastructure
poetry run ccwb package                    # build platform installers
poetry run ccwb distribute                 # upload packages / generate URLs
poetry run ccwb test                       # verify deployment
poetry run ccwb destroy                    # tear down AWS resources

# Profile management
poetry run ccwb context list               # list profiles
poetry run ccwb context use <name>         # switch profile
poetry run ccwb context show               # show active profile

# Inference profile management
poetry run ccwb profiles list              # list user's Application Inference Profile ARNs
poetry run ccwb profiles set-default <key> # switch default model in ~/.claude.json

# Quota management
poetry run ccwb quota set-user <email> --monthly-limit 500M --daily-limit 20M
poetry run ccwb quota set-group <group> --monthly-limit 400M
poetry run ccwb quota set-default --monthly-limit 225M
poetry run ccwb quota list                 # list all policies
poetry run ccwb quota show <email>         # effective policy for a user
poetry run ccwb quota usage <email>        # current usage against limits
poetry run ccwb quota export policies.json # export policies
poetry run ccwb quota import users.csv     # bulk import policies
```

## Versioning

- Version lives in `source/pyproject.toml` under `[tool.poetry] version`
- CHANGELOG.md must be updated in the same PR as any version bump
- Follows Semantic Versioning (semver)
