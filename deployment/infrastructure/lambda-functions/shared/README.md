# Shared Lambda Utilities

Common utilities shared across Lambda functions for Claude Code with Bedrock.

## Modules

### `pricing.py`
Bedrock pricing data for quota and cost calculations.

### `mdm_config.py`
MDM configuration schema, constants, and builder functions.

**Key exports:**
- `ALL_MDM_KEYS` - Complete set of valid MDM keys
- `DEFAULT_POLICIES` - Default feature toggle values
- `normalize_model_id()` - Ensure model IDs have proper prefix
- `build_inference_models()` - Build inferenceModels array from model specs
- `build_base_config()` - Create base MDM config with common settings
- `add_idc_sso_config()` - Add IAM Identity Center SSO settings
- `add_bootstrap_config()` - Add dynamic bootstrap configuration
- `add_policies()` - Add tool/feature policies
- `add_mcp_servers()` - Add MCP server configuration

### `mdm_generators.py`
Platform-specific MDM file generators.

**Key exports:**
- `generate_mobileconfig()` - Generate macOS mobileconfig XML
- `generate_reg_file()` - Generate Windows registry file
- `generate_json_config()` - Generate JSON config file

## Usage

### In Lambda Functions

```python
from shared.mdm_config import (
    build_base_config,
    add_idc_sso_config,
    add_bootstrap_config,
)
from shared.mdm_generators import generate_mobileconfig

# Build config
config = build_base_config(
    bedrock_region="us-east-1",
    models=[{"modelId": "us.anthropic.claude-sonnet-4", "modelName": "Sonnet 4"}],
)
add_idc_sso_config(config, start_url, region, account_id, role_name)
add_bootstrap_config(config, bootstrap_url, oidc_config)

# Generate platform files
mobileconfig_xml = generate_mobileconfig(config, "my-profile", "My Profile")
```

### In ccwb CLI

The `ccwb cowork generate` command uses `source/claude_code_with_bedrock/cli/utils/cowork_3p.py` which should be aligned with these shared utilities.

## Alignment Status

| Component | Uses Shared Library | Notes |
|-----------|---------------------|-------|
| `bootstrap_server/index.py` | Partial | Uses own config builder |
| `bootstrap_device_code/index.py` | No | Needs migration |
| `idc-landing-page/lambda/index.py` | No | Needs migration (shared module copied) |
| `ccwb cowork generate` | No | Uses `cowork_3p.py` |

## Migration Plan

1. **Phase 1 (Complete)**: Create shared library with canonical MDM schema
2. **Phase 2**: Update `bootstrap_server/index.py` to use shared builders
3. **Phase 3**: Update `idc-landing-page/lambda/index.py` to use shared generators
4. **Phase 4**: Align `cowork_3p.py` with shared library (may need to import or mirror)
5. **Phase 5**: Add validation tests to ensure all generators produce compatible output
