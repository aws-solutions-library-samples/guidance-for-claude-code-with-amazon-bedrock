# Integration Plan: IDC Landing Page into ccwb CLI

This document outlines how to integrate the IDC Landing Page into the `ccwb` CLI workflow.

## Current State

### Existing Distribution Flow
```
ccwb init → distribution_type: "landing-page" → distribution_idp_provider: okta|azure|auth0|cognito|generic
ccwb deploy --stack distribution → landing-page-distribution.yaml (ALB + Lambda + external OIDC)
```

### IDC Landing Page (Standalone)
```
cd deployment/idc-landing-page
npx cdk deploy → Cognito + CloudFront + Lambda (IDC-native, admin UI, permission set automation)
```

## Proposed Integration

### Option A: New Distribution Type (Recommended)

Add `landing-page-idc` as a new distribution type that uses CDK instead of CloudFormation.

**Config Changes (`config.py`):**
```python
distribution_type: str | None = None  # "presigned-s3" | "landing-page" | "landing-page-idc" | None
distribution_idc_instance_arn: str | None = None  # IAM Identity Center instance ARN
distribution_idc_bootstrap_client_id: str | None = None  # Cognito bootstrap client ID
```

**Init Wizard Changes (`init.py`):**
```python
distribution_choices = [
    questionary.Choice("Presigned S3 URLs (simple)", value="presigned-s3"),
    questionary.Choice("Landing Page (external OIDC)", value="landing-page"),
    questionary.Choice("Landing Page (IAM Identity Center)", value="landing-page-idc"),  # NEW
    questionary.Choice("Disabled", value=None),
]

# When landing-page-idc selected:
if distribution_type == "landing-page-idc":
    # Prompt for IDC instance ARN
    idc_instance_arn = questionary.text(
        "IAM Identity Center instance ARN:",
        default=config.get("distribution", {}).get("idc_instance_arn", ""),
    ).ask()
    config["distribution"]["idc_instance_arn"] = idc_instance_arn
```

**Deploy Changes (`deploy.py`):**
```python
elif profile.distribution_type == "landing-page-idc":
    # Use CDK instead of CloudFormation
    cdk_dir = project_root / "deployment" / "idc-landing-page"
    
    # Write config.ts with profile values
    config_content = f'''
export const config: LandingPageConfig = {{
  profileName: '{profile.identity_pool_name}',
  idcInstanceArn: '{profile.distribution_idc_instance_arn}',
  region: '{profile.aws_region}',
  account: '{account_id}',
  bootstrapOidcClientId: '{profile.distribution_idc_bootstrap_client_id or ""}',
}};
'''
    (cdk_dir / "lib" / "config.ts").write_text(config_content)
    
    # Deploy CDK
    subprocess.run(["npx", "cdk", "deploy", "--all", "--require-approval", "never"], cwd=cdk_dir)
```

### Option B: Hybrid CloudFormation + Post-Deploy Script

Convert CDK to CloudFormation and add manual SAML setup steps.

**Pros:** Stays within existing cfn-based workflow
**Cons:** Loses CDK benefits, complex SAML setup still manual

### Option C: Separate Command

Add a dedicated `ccwb idc-portal` command:

```bash
ccwb idc-portal init      # Configure IDC landing page
ccwb idc-portal deploy    # Deploy CDK stack
ccwb idc-portal destroy   # Tear down
```

**Pros:** Clean separation, doesn't clutter existing commands
**Cons:** Different workflow, users need to learn new command

## Recommended Implementation: Option A

### Phase 1: Add Config Fields

```python
# config.py
distribution_idc_instance_arn: str | None = None
distribution_idc_bootstrap_client_id: str | None = None
distribution_idc_admin_group: str = "Claude-Code-Admins"
```

### Phase 2: Update Init Wizard

Add `landing-page-idc` choice and IDC-specific prompts:
- IDC instance ARN (auto-detect if possible)
- Admin group name (default: Claude-Code-Admins)

### Phase 3: Update Deploy Command

For `landing-page-idc`:
1. Generate `config.ts` from profile
2. Run `npm install` if needed
3. Run `npx cdk deploy --all`
4. Store outputs (CloudFront URL) in profile

### Phase 4: Update Destroy Command

For `landing-page-idc`:
1. Run `npx cdk destroy --all`

### Phase 5: Documentation

Update QUICK_START.md and docs with new option.

## Post-Deploy Manual Steps

Some steps require manual configuration in AWS Console:

1. **Configure SAML in IAM Identity Center**
   - Create custom SAML 2.0 application
   - Set ACS URL and Audience from CDK outputs
   - Map attributes (Subject, email)
   - Assign groups

2. **Configure Cognito Identity Provider**
   - Add SAML provider with metadata URL
   - Enable in app clients

3. **Create Bootstrap OIDC Client**
   - Create Cognito app client (no secret)
   - Add callback URL
   - Update config and redeploy

These could be partially automated with `ccwb idc-portal setup` in the future.

## File Changes Summary

| File | Change |
|------|--------|
| `source/claude_code_with_bedrock/config.py` | Add IDC distribution fields |
| `source/claude_code_with_bedrock/cli/commands/init.py` | Add landing-page-idc option and prompts |
| `source/claude_code_with_bedrock/cli/commands/deploy.py` | Add CDK deployment for landing-page-idc |
| `source/claude_code_with_bedrock/cli/commands/destroy.py` | Add CDK destroy for landing-page-idc |
| `source/claude_code_with_bedrock/cli/commands/configure_saml.py` | Automate Cognito SAML provider setup after manual IAM Identity Center app creation (`ccwb configure-saml <metadata-url>`) |
| `source/claude_code_with_bedrock/validators.py` | Add validation for IDC distribution fields |
| `QUICK_START.md` | Document new option |

## Timeline Estimate

- Phase 1: 1 hour (config fields)
- Phase 2: 2-3 hours (init wizard)
- Phase 3: 2-3 hours (deploy command)
- Phase 4: 1 hour (destroy command)
- Phase 5: 1 hour (documentation)

**Total: ~8-10 hours**
