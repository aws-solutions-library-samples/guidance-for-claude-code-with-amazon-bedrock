# CLAUDE.md

Project rules for AI coding agents. Detailed rules in `.claude/rules/`.

## Repository
AWS guidance for Claude Code with Amazon Bedrock. Python CLI (`ccwb`) + Go credential-process binary + CloudFormation templates.

## Branch Strategy
- Target branch: `beta` (not `main`)
- Rebase onto latest `upstream/beta` before opening PRs
- `main` is release-only

## Architecture
```
ccwb init (wizard) → config.yaml → ccwb deploy → CloudFormation templates
                                  → ccwb package → config.json + binary → credential-process (Go)
```

### Key files
- `source/claude_code_with_bedrock/config.py` — Profile dataclass
- `source/claude_code_with_bedrock/cli/commands/init.py` — Setup wizard
- `source/claude_code_with_bedrock/cli/commands/deploy.py` — Stack deployment
- `source/claude_code_with_bedrock/cli/commands/package.py` — Binary packaging
- `source/go/cmd/credential-process/main.go` — Go credential provider
- `source/go/internal/config/config.go` — Go config struct
- `deployment/infrastructure/` — CloudFormation templates

## Testing
- `cd source && poetry run pytest tests/ -q` before pushing
- Must pass Linux, macOS, AND Windows (CI matrix)
- Windows tests are blocking
- Every fix needs a regression test