# ABOUTME: Configuration validators run at package time to catch misconfigurations early.
# ABOUTME: Called by the package command before generating any distribution files.

"""Configuration validators run at package time to catch misconfigurations early."""

from dataclasses import dataclass


@dataclass
class ValidationError:
    field: str
    message: str
    severity: str = "error"  # "error" or "warning"


def validate_profile_for_packaging(profile) -> list[ValidationError]:
    """Validate a profile is consistent and ready for packaging."""
    errors = []

    auth_type = getattr(profile, "effective_auth_type", getattr(profile, "auth_type", "oidc"))

    # IDC requires start URL
    if auth_type == "idc":
        if not getattr(profile, "idc_start_url", None):
            errors.append(ValidationError("idc_start_url", "IDC auth requires idc_start_url"))
        if not getattr(profile, "idc_account_id", None):
            errors.append(ValidationError("idc_account_id", "IDC auth requires idc_account_id"))
        if not getattr(profile, "idc_permission_set_name", None):
            errors.append(ValidationError("idc_permission_set_name", "IDC auth requires idc_permission_set_name"))

    # OIDC requires provider domain + client ID
    if auth_type == "oidc":
        if not getattr(profile, "provider_domain", None) and not getattr(profile, "oidc_issuer_url", None):
            errors.append(ValidationError("provider_domain", "OIDC auth requires provider_domain or oidc_issuer_url"))
        if not getattr(profile, "client_id", None):
            errors.append(ValidationError("client_id", "OIDC auth requires client_id"))

    # Region validation
    if not getattr(profile, "aws_region", None):
        errors.append(ValidationError("aws_region", "AWS region is required"))

    allowed_regions = getattr(profile, "allowed_bedrock_regions", None)
    if allowed_regions and getattr(profile, "aws_region", None):
        # Expand model region sentinels (e.g. "all-commercial") before comparing —
        # a global-model profile legitimately stores the sentinel, which expands to
        # include aws_region. Comparing against the raw list warned spuriously.
        from claude_code_with_bedrock.models import expand_bedrock_regions

        effective_regions = expand_bedrock_regions(allowed_regions)
        if profile.aws_region not in effective_regions:
            errors.append(
                ValidationError(
                    "aws_region",
                    f"Region '{profile.aws_region}' not in allowed_bedrock_regions: {allowed_regions}",
                    severity="warning",
                )
            )

    # Monitoring consistency — CENTRAL mode only. Sidecar packages hardcode
    # the local collector endpoint (http://localhost:4318) at package time and
    # never have an ALB endpoint in the profile, so this warning was spurious
    # for every sidecar deployment — and its advice (deploy the central
    # monitoring stack) is exactly what sidecar mode must NOT do.
    if getattr(profile, "monitoring_enabled", False) and getattr(profile, "monitoring_mode", "central") == "central":
        endpoint = getattr(profile, "otel_collector_endpoint", None)
        config_mode = getattr(profile, "cowork_config_mode", "static")
        if not endpoint and config_mode != "dynamic":
            errors.append(
                ValidationError(
                    "otel_collector_endpoint",
                    "Monitoring enabled but no otel_collector_endpoint configured (and not using bootstrap server). "
                    "Run 'ccwb deploy --stack monitoring' first.",
                    severity="warning",
                )
            )

    # Bootstrap server + IDC conflict
    if getattr(profile, "cowork_config_mode", "static") == "dynamic" and auth_type == "idc":
        errors.append(
            ValidationError(
                "cowork_config_mode",
                "Bootstrap server (dynamic config) is not supported with IDC auth. Use static MDM profiles.",
            )
        )

    # Quota enforcement requires quota API endpoint
    if getattr(profile, "quota_enforcement_mode", "off") != "off":
        if not getattr(profile, "quota_api_endpoint", None):
            errors.append(
                ValidationError(
                    "quota_api_endpoint",
                    f"Quota enforcement mode '{profile.quota_enforcement_mode}' requires quota_api_endpoint",
                )
            )

    return errors
