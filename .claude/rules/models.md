---
paths:
  - "source/claude_code_with_bedrock/models.py"
---

# Model Configuration Rules

## This file is the single source of truth for all Claude model definitions.

## Model ID Format
- Pattern: `{profile}.anthropic.{model}-{date}-v{version}:0`
- Example: `us.anthropic.claude-sonnet-4-6-20250514-v1:0`
- GovCloud uses `us-gov.` prefix

## Cross-Region Profiles
- `us`: Routes across US commercial regions
- `europe`: Routes across EU regions
- `apac`: Routes across Asia-Pacific regions
- `us-gov`: Routes across GovCloud regions

## Region Types
- **Source regions**: Where AWS CLI/SDK requests originate (user's configured region)
- **Destination regions**: Where Bedrock routes inference requests (transparent to user)

## When Modifying
- Update ALL profiles if adding a new model (us, europe, apac, us-gov)
- Verify model availability in each region before adding
- Run `poetry run pytest tests/test_models.py -v` after changes
- Ensure backward compatibility — existing configs reference model IDs
