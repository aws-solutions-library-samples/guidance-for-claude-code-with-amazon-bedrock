# ABOUTME: Profile validation utilities for Claude Code with Bedrock
# ABOUTME: Comprehensive validation rules for profile configurations

"""Profile validation for Claude Code with Bedrock."""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

# AWS regions (as of 2025)
AWS_REGIONS = {
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "ca-central-1",
    "eu-central-1",
    "eu-central-2",
    "eu-west-1",
    "eu-west-2",
    "eu-west-3",
    "eu-north-1",
    "eu-south-1",
    "eu-south-2",
    "eu-south-3",
    "ap-south-1",
    "ap-south-5",
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-northeast-3",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-southeast-3",
    "ap-southeast-4",
    "ap-east-1",
    "sa-east-1",
    "me-south-1",
    "me-central-1",
    "af-south-1",
}


@dataclass
class ValidationResult:
    """Result of profile validation."""

    valid: bool
    errors: list[str]
    warnings: list[str]

    def __bool__(self) -> bool:
        """Return True if validation passed (no errors)."""
        return self.valid

    def __str__(self) -> str:
        """String representation of validation result."""
        if self.valid:
            msg = "✓ Validation passed"
            if self.warnings:
                msg += f" ({len(self.warnings)} warning(s))"
            return msg
        else:
            msg = f"✗ Validation failed ({len(self.errors)} error(s))"
            if self.warnings:
                msg += f", {len(self.warnings)} warning(s)"
            return msg


class ProfileValidator:
    """Validator for Profile configurations."""

    @staticmethod
    def validate_profile(profile_data: dict[str, Any]) -> ValidationResult:
        """Validate a profile configuration.

        Args:
            profile_data: Profile data dictionary to validate.

        Returns:
            ValidationResult with errors and warnings.
        """
        errors = []
        warnings = []

        # Required fields
        required_fields = [
            "name",
            "provider_domain",
            "client_id",
            "credential_storage",
            "aws_region",
            "identity_pool_name",
        ]

        for field in required_fields:
            if field not in profile_data or not profile_data[field]:
                errors.append(f"Required field '{field}' is missing or empty")

        # If basic required fields are missing, return early
        if errors:
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        # Validate profile name format
        name = profile_data.get("name", "")
        if not ProfileValidator._is_valid_profile_name(name):
            errors.append(
                f"Invalid profile name '{name}'. " "Must be alphanumeric with hyphens only, max 64 characters"
            )

        # Validate provider domain format
        domain = profile_data.get("provider_domain", "")
        if domain and not ProfileValidator._is_valid_domain(domain):
            errors.append(f"Invalid provider_domain format: {domain}")

        # Validate AWS region
        region = profile_data.get("aws_region", "")
        if region and region not in AWS_REGIONS:
            errors.append(f"Invalid aws_region: {region}")

        # Validate credential storage
        cred_storage = profile_data.get("credential_storage", "")
        if cred_storage and cred_storage not in ["keyring", "session"]:
            errors.append(f"Invalid credential_storage: {cred_storage}. Must be 'keyring' or 'session'")

        # Validate provider type if specified
        provider_type = profile_data.get("provider_type")
        if provider_type and provider_type not in ["okta", "auth0", "azure", "cognito"]:
            warnings.append(f"Unknown provider_type: {provider_type}")

        # Conditional validation: Cognito requires user_pool_id
        if provider_type == "cognito":
            user_pool_id = profile_data.get("cognito_user_pool_id")
            if not user_pool_id:
                errors.append("cognito_user_pool_id is required when provider_type is 'cognito'")
            elif not ProfileValidator._is_valid_cognito_user_pool_id(user_pool_id):
                errors.append(f"Invalid cognito_user_pool_id format: {user_pool_id}")

        # Validate federation type
        federation_type = profile_data.get("federation_type", "cognito")
        if federation_type not in ["cognito", "direct"]:
            errors.append(f"Invalid federation_type: {federation_type}. Must be 'cognito' or 'direct'")

        # Conditional: Direct federation requires federated_role_arn
        if federation_type == "direct":
            role_arn = profile_data.get("federated_role_arn")
            if not role_arn:
                errors.append("federated_role_arn is required when federation_type is 'direct'")
            elif not ProfileValidator._is_valid_arn(role_arn):
                errors.append(f"Invalid federated_role_arn format: {role_arn}")

        # Validate distribution configuration
        distribution_type = profile_data.get("distribution_type")
        if distribution_type:
            if distribution_type not in ["presigned-s3", "landing-page"]:
                errors.append(
                    f"Invalid distribution_type: {distribution_type}. " "Must be 'presigned-s3' or 'landing-page'"
                )

            # Landing page requires additional fields
            if distribution_type == "landing-page":
                dist_provider = profile_data.get("distribution_idp_provider")
                if not dist_provider:
                    errors.append("distribution_idp_provider is required for landing-page distribution")
                elif dist_provider not in ["okta", "auth0", "azure", "cognito"]:
                    errors.append(
                        f"Invalid distribution_idp_provider: {dist_provider}. "
                        "Must be 'okta', 'auth0', 'azure', or 'cognito'"
                    )

                dist_domain = profile_data.get("distribution_idp_domain")
                if not dist_domain:
                    errors.append("distribution_idp_domain is required for landing-page distribution")

                dist_client_id = profile_data.get("distribution_idp_client_id")
                if not dist_client_id:
                    errors.append("distribution_idp_client_id is required for landing-page distribution")

                # Check for secret ARN
                secret_arn = profile_data.get("distribution_idp_client_secret_arn")
                if secret_arn and not ProfileValidator._is_valid_arn(secret_arn):
                    errors.append(f"Invalid distribution_idp_client_secret_arn format: {secret_arn}")

                # Custom domain validation
                custom_domain = profile_data.get("distribution_custom_domain")
                if custom_domain and not ProfileValidator._is_valid_domain(custom_domain):
                    errors.append(f"Invalid distribution_custom_domain format: {custom_domain}")

        # Validate allowed_bedrock_regions
        allowed_regions = profile_data.get("allowed_bedrock_regions", [])
        if allowed_regions:
            if not isinstance(allowed_regions, list):
                errors.append("allowed_bedrock_regions must be a list")
            else:
                for bedrock_region in allowed_regions:
                    if bedrock_region not in AWS_REGIONS:
                        warnings.append(f"Unknown Bedrock region: {bedrock_region}")

        # Validate cross_region_profile
        cross_region = profile_data.get("cross_region_profile")
        if cross_region:
            valid_profiles = ["us", "europe", "apac", "global", "japan", "eu"]
            if cross_region not in valid_profiles:
                warnings.append(
                    f"Unknown cross_region_profile: {cross_region}. " f"Expected one of: {', '.join(valid_profiles)}"
                )

        # Validate quota settings
        monthly_limit = profile_data.get("monthly_token_limit")
        if monthly_limit is not None:
            if not isinstance(monthly_limit, int) or monthly_limit <= 0:
                errors.append("monthly_token_limit must be a positive integer")
            elif monthly_limit > 1_000_000_000:
                warnings.append(
                    f"monthly_token_limit is very high ({monthly_limit:,} tokens). "
                    "This may be intentional, but please verify."
                )

        # Validate session duration
        max_duration = profile_data.get("max_session_duration")
        if max_duration is not None:
            if not isinstance(max_duration, int):
                errors.append("max_session_duration must be an integer (seconds)")
            elif max_duration < 3600 or max_duration > 43200:
                warnings.append(f"max_session_duration ({max_duration}s) is outside typical range (3600-43200s)")

        # Validate data retention
        retention_days = profile_data.get("data_retention_days")
        if retention_days is not None:
            if not isinstance(retention_days, int) or retention_days <= 0:
                errors.append("data_retention_days must be a positive integer")
            elif retention_days > 365:
                warnings.append(
                    f"data_retention_days ({retention_days}) is over 1 year. " "This may incur significant costs."
                )

        # Validate schema version
        schema_version = profile_data.get("schema_version")
        if schema_version and schema_version not in ["1.0", "2.0"]:
            warnings.append(f"Unknown schema_version: {schema_version}")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _is_valid_profile_name(name: str) -> bool:
        """Validate profile name format.

        Args:
            name: Profile name to validate.

        Returns:
            True if valid, False otherwise.
        """
        if not name or len(name) > 64:
            return False
        return bool(re.match(r"^[a-zA-Z0-9\-]+$", name))

    @staticmethod
    def _is_valid_domain(domain: str) -> bool:
        """Validate domain format.

        Args:
            domain: Domain to validate.

        Returns:
            True if valid, False otherwise.
        """
        if not domain:
            return False

        # Handle both full URLs and domain-only inputs
        url_to_parse = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"

        try:
            parsed = urlparse(url_to_parse)
            hostname = parsed.hostname

            if not hostname:
                return False

            # Basic domain format check
            # Must have at least one dot and valid characters
            domain_pattern = (
                r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
            )
            return bool(re.match(domain_pattern, hostname))

        except Exception:
            return False

    @staticmethod
    def _is_valid_arn(arn: str) -> bool:
        """Validate AWS ARN format.

        Args:
            arn: ARN to validate.

        Returns:
            True if valid, False otherwise.
        """
        if not arn:
            return False

        # Basic ARN format: arn:partition:service:region:account-id:resource
        arn_pattern = r"^arn:[a-z\-]+:[a-z0-9\-]+:[a-z0-9\-]*:\d{12}:.+$"
        return bool(re.match(arn_pattern, arn))

    @staticmethod
    def _is_valid_cognito_user_pool_id(pool_id: str) -> bool:
        """Validate Cognito User Pool ID format.

        Args:
            pool_id: User Pool ID to validate.

        Returns:
            True if valid, False otherwise.
        """
        if not pool_id:
            return False

        # Format: {region}_{alphanumeric}
        # Example: us-east-1_rFo2lol9W
        pool_pattern = r"^[a-z]{2}-[a-z]+-\d+_[a-zA-Z0-9]+$"
        return bool(re.match(pool_pattern, pool_id))


def validate_profile(profile_data: dict[str, Any]) -> ValidationResult:
    """Convenience function to validate a profile.

    Args:
        profile_data: Profile data dictionary to validate.

    Returns:
        ValidationResult with errors and warnings.
    """
    return ProfileValidator.validate_profile(profile_data)
