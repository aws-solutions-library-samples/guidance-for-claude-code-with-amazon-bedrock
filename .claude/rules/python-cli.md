---
paths:
  - "source/claude_code_with_bedrock/**/*.py"
---

# Python CLI Development Rules

## CLI Framework
- Built on Cleo (Symfony Console for Python) — not Click or argparse
- Commands inherit from `cleo.commands.Command`
- Register new commands in `source/claude_code_with_bedrock/cli/__init__.py`
- Interactive prompts use `questionary`, not Cleo's built-in helpers

## Configuration
- Profile config lives in `~/.ccwb/` (migrated from `source/.ccwb-config/`)
- Use `config.py` data models (Pydantic) for all config access
- Never hardcode AWS regions, model IDs, or provider URLs

## AWS Interactions
- Use `boto3.client()` for all AWS calls
- Wrap in try/except for `ClientError` and `BotoCoreError`
- Region comes from profile config, not environment variables
- All AWS utilities live in `cli/utils/aws.py`

## Code Style
- Line length: 120 characters (configured in ruff/black)
- Python 3.10+ features allowed (match/case, union types with `|`)
- Use `rich` for terminal formatting (tables, panels, progress bars)
- Type hints required on public functions

## Adding a New Command
1. Create `source/claude_code_with_bedrock/cli/commands/<name>.py`
2. Inherit from `cleo.commands.Command`
3. Register in `cli/__init__.py`
4. Create `tests/cli/commands/test_<name>.py`
5. Update `CLI_REFERENCE.md`
