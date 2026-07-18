# ABOUTME: Shared utilities package for Lambda functions (pricing, MDM config, common helpers).

from .mdm_config import (
    ALL_MDM_KEYS,
    DEFAULT_INFERENCE_REGION,
    DEFAULT_POLICIES,
    DEFAULT_SESSION_LIFETIME_SEC,
    MDM_KEYS_BOOTSTRAP,
    MDM_KEYS_IDC_SSO,
    MDM_KEYS_INFERENCE,
    MDM_KEYS_MCP,
    MDM_KEYS_ORG,
    MDM_KEYS_POLICIES,
    MDM_KEYS_RESTRICTIONS,
    MDM_KEYS_TELEMETRY,
    add_bootstrap_config,
    add_idc_sso_config,
    add_mcp_servers,
    add_policies,
    add_telemetry_config,
    build_base_config,
    build_inference_models,
    infer_model_tier,
    normalize_model_id,
)
from .mdm_generators import (
    generate_json_config,
    generate_mobileconfig,
    generate_reg_file,
)

__all__ = [
    # MDM key definitions
    "ALL_MDM_KEYS",
    "MDM_KEYS_INFERENCE",
    "MDM_KEYS_IDC_SSO",
    "MDM_KEYS_BOOTSTRAP",
    "MDM_KEYS_POLICIES",
    "MDM_KEYS_RESTRICTIONS",
    "MDM_KEYS_MCP",
    "MDM_KEYS_TELEMETRY",
    "MDM_KEYS_ORG",
    # Defaults
    "DEFAULT_INFERENCE_REGION",
    "DEFAULT_SESSION_LIFETIME_SEC",
    "DEFAULT_POLICIES",
    # Model utilities
    "normalize_model_id",
    "infer_model_tier",
    "build_inference_models",
    # Config builders
    "build_base_config",
    "add_idc_sso_config",
    "add_bootstrap_config",
    "add_policies",
    "add_mcp_servers",
    "add_telemetry_config",
    # Generators
    "generate_mobileconfig",
    "generate_reg_file",
    "generate_json_config",
]
