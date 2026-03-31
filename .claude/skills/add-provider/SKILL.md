---
name: add-provider
description: "Scaffold support for a new identity provider (IdP) with CloudFormation template, validator logic, and documentation. Use when the user wants to add support for a new OIDC provider like Ping Identity, Google Workspace, OneLogin, or any other identity provider."
user-invocable: true
argument-hint: "<provider-name>"
---

# Add New Identity Provider

Scaffold full support for a new OIDC identity provider. Provider: $ARGUMENTS

## Steps

1. **Study an existing provider** for reference patterns:
   - Read `deployment/infrastructure/bedrock-auth-okta.yaml` (CloudFormation template)
   - Read `source/claude_code_with_bedrock/validators.py` (provider detection)
   - Read `source/claude_code_with_bedrock/cli/commands/init.py` (wizard flow)

2. **Create CloudFormation template** at:
   ```
   deployment/infrastructure/bedrock-auth-<provider>.yaml
   ```

   Must include:
   - IAM OIDC Provider resource
   - IAM Role with AssumeRoleWithWebIdentity trust policy
   - Bedrock access policy (scoped to specific models)
   - Session tag mappings for CloudTrail attribution
   - Use `${AWS::Partition}` for all ARNs (multi-partition support)
   - Outputs: RoleArn, ProviderArn

3. **Add provider detection** in `source/claude_code_with_bedrock/validators.py`:
   - Pattern match on the OIDC issuer URL
   - Return provider type enum

4. **Update init wizard** in `source/claude_code_with_bedrock/cli/commands/init.py`:
   - Add provider to the selection list
   - Add provider-specific prompts (e.g., tenant ID for Azure)

5. **Create setup documentation** at:
   ```
   assets/docs/providers/<provider>-setup.md
   ```

6. **Validate everything**:
   ```bash
   poetry run cfn-lint deployment/infrastructure/bedrock-auth-<provider>.yaml
   cd source && poetry run pytest tests/ -v
   ```
