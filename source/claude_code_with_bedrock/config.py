# ABOUTME: Configuration management for Claude Code with Bedrock
# ABOUTME: Handles profiles, settings persistence, and configuration validation

"""Configuration management for Claude Code with Bedrock."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Profile:
    """Configuration profile for a deployment."""

    name: str
    provider_domain: str  # Generic OIDC provider domain (was okta_domain)
    client_id: str  # Generic OIDC client ID (was okta_client_id)
    credential_storage: str  # Storage method: "keyring" (OS keyring) or "session" (~/.aws/credentials)
    aws_region: str
    identity_pool_name: str
    schema_version: str = "2.0"  # Configuration schema version
    stack_names: dict[str, str] = field(default_factory=dict)
    monitoring_enabled: bool = True
    monitoring_config: dict[str, Any] = field(default_factory=dict)
    analytics_enabled: bool = True  # Analytics pipeline for user metrics
    metrics_log_group: str = "/aws/claude-code/metrics"
    data_retention_days: int = 90
    firehose_buffer_interval: int = 900
    analytics_debug_mode: bool = False
    allowed_bedrock_regions: list[str] = field(default_factory=list)
    cross_region_profile: str | None = None  # Cross-region profile: "us", "europe", "apac"
    selected_model: str | None = None  # Selected Claude model ID (e.g., "us.anthropic.claude-3-7-sonnet-20250805-v1:0")
    selected_source_region: str | None = None  # User-selected source region for AWS config and Claude Code settings
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    provider_type: str | None = None  # Auto-detected: "okta", "auth0", "azure", "cognito"
    cognito_user_pool_id: str | None = None  # Only for Cognito User Pool providers
    enable_codebuild: bool = False  # Enable CodeBuild for Windows binary builds
    enable_distribution: bool = False  # Enable package distribution features (legacy, use distribution_type)

    # Distribution platform configuration
    distribution_type: str | None = None  # "presigned-s3" | "landing-page" | None (disabled)
    distribution_idp_provider: str | None = None  # "okta" | "azure" | "auth0" | "cognito" (for landing-page only)
    distribution_idp_domain: str | None = None  # IdP domain for web auth (e.g., "company.okta.com")
    distribution_idp_client_id: str | None = None  # Web application client ID
    distribution_idp_client_secret_arn: str | None = None  # Secrets Manager ARN for client secret
    distribution_custom_domain: str | None = None  # Optional custom domain (e.g., "downloads.company.com")
    distribution_hosted_zone_id: str | None = None  # Optional Route53 hosted zone ID

    # Quota monitoring configuration
    quota_monitoring_enabled: bool = False  # Enable per-user token quota monitoring
    monthly_token_limit: int = 10000000  # Monthly token limit per user (10M default)
    warning_threshold_80: int = 8000000  # Warning threshold at 80% (8M default)
    warning_threshold_90: int = 9000000  # Critical threshold at 90% (9M default)
    enable_finegrained_quotas: bool = False  # Enable fine-grained quota policies (user/group/default)
    quota_policies_table: str | None = None  # DynamoDB table name for quota policies
    user_quota_metrics_table: str | None = None  # DynamoDB table name for user quota metrics
    quota_api_endpoint: str | None = None  # API Gateway endpoint for real-time quota checks
    quota_fail_mode: str = "open"  # "open" (allow on error) or "closed" (deny on error)

    # Federation configuration
    federation_type: str = "cognito"  # "cognito" or "direct"
    federated_role_arn: str | None = None  # ARN for Direct STS federation
    max_session_duration: int = 28800  # 8 hours default, 43200 (12 hours) for Direct STS

    # Claude Code settings configuration
    include_coauthored_by: bool = True  # Whether to include "co-authored-by Claude" in git commits

    # Legacy field support
    @property
    def okta_domain(self) -> str:
        """Legacy property for backward compatibility."""
        return self.provider_domain

    @property
    def okta_client_id(self) -> str:
        """Legacy property for backward compatibility."""
        return self.client_id

    def to_dict(self) -> dict[str, Any]:
        """Convert profile to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        """Create profile from dictionary with migration support."""
        # Set schema_version if not present (migrating from v1.0)
        if "schema_version" not in data:
            data["schema_version"] = "2.0"

        # Migrate old field names to new ones
        if "okta_domain" in data and "provider_domain" not in data:
            data["provider_domain"] = data.pop("okta_domain")
        if "okta_client_id" in data and "client_id" not in data:
            data["client_id"] = data.pop("okta_client_id")

        # Remove any remaining old fields to avoid conflicts
        data.pop("okta_domain", None)
        data.pop("okta_client_id", None)

        # Provide default for credential_storage if not present
        if "credential_storage" not in data:
            data["credential_storage"] = "session"

        # Auto-detect provider type if not set
        if "provider_type" not in data and "provider_domain" in data:
            domain = data["provider_domain"]
            # Secure provider detection using proper URL parsing
            if domain:
                # Handle both full URLs and domain-only inputs
                url_to_parse = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"

                try:
                    from urllib.parse import urlparse

                    parsed = urlparse(url_to_parse)
                    hostname = parsed.hostname

                    if hostname:
                        hostname_lower = hostname.lower()

                        # Check for exact domain match or subdomain match
                        # Using endswith with leading dot prevents bypass attacks
                        if hostname_lower.endswith(".okta.com") or hostname_lower == "okta.com":
                            data["provider_type"] = "okta"
                        elif hostname_lower.endswith(".auth0.com") or hostname_lower == "auth0.com":
                            data["provider_type"] = "auth0"
                        elif hostname_lower.endswith(".microsoftonline.com") or hostname_lower == "microsoftonline.com":
                            data["provider_type"] = "azure"
                        elif hostname_lower.endswith(".windows.net") or hostname_lower == "windows.net":
                            data["provider_type"] = "azure"
                        elif hostname_lower.endswith(".amazoncognito.com") or hostname_lower == "amazoncognito.com":
                            data["provider_type"] = "cognito"
                except Exception:
                    pass  # Leave provider_type unset if parsing fails

        # Migrate legacy distribution configuration
        if "enable_distribution" in data and data.get("enable_distribution"):
            # If distribution was enabled but no type specified, default to presigned-s3
            if "distribution_type" not in data or data["distribution_type"] is None:
                data["distribution_type"] = "presigned-s3"

        # Set default cross-region profile if not present
        if "cross_region_profile" not in data:
            # Default to 'us' for existing deployments with US regions
            if "allowed_bedrock_regions" in data:
                regions = data["allowed_bedrock_regions"]
                if any(r.startswith("us-") for r in regions):
                    data["cross_region_profile"] = "us"

        return cls(**data)


class Config:
    """Configuration manager for Claude Code with Bedrock."""

    # New location in user home directory
    CONFIG_DIR = Path.home() / ".ccwb"
    CONFIG_FILE = CONFIG_DIR / "config.json"
    PROFILES_DIR = CONFIG_DIR / "profiles"

    # Legacy location for migration
    LEGACY_CONFIG_DIR = Path(__file__).parent.parent / ".ccwb-config"
    LEGACY_CONFIG_FILE = LEGACY_CONFIG_DIR / "config.json"

    def __init__(self, active_profile: str | None = None, schema_version: str = "2.0"):
        """Initialize configuration."""
        self.active_profile = active_profile
        self.schema_version = schema_version
        self._ensure_config_dir()

    def _ensure_config_dir(self) -> None:
        """Ensure configuration directories exist."""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls) -> "Config":
        """Load global configuration from file, with auto-migration from legacy location."""
        # Check if migration is needed
        if not cls.CONFIG_FILE.exists() and cls.LEGACY_CONFIG_FILE.exists():
            from .migration import migrate_legacy_config

            migrate_legacy_config()

        # Load global config
        if cls.CONFIG_FILE.exists():
            try:
                with open(cls.CONFIG_FILE) as f:
                    data = json.load(f)

                return cls(
                    active_profile=data.get("active_profile"),
                    schema_version=data.get("schema_version", "2.0"),
                )

            except Exception as e:
                print(f"Warning: Could not load config: {e}")
                return cls()
        else:
            return cls()

    def save(self) -> None:
        """Save global configuration to file."""
        data = {
            "schema_version": self.schema_version,
            "active_profile": self.active_profile,
            "profiles_dir": str(self.PROFILES_DIR),
        }

        with open(self.CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def load_profile(self, name: str | None = None) -> Profile:
        """Load a specific profile or the active profile.

        Args:
            name: Profile name to load. If None, loads active profile.

        Returns:
            Profile object.

        Raises:
            ValueError: If no profile specified and no active profile set.
            FileNotFoundError: If profile file doesn't exist.
        """
        profile_name = name or self.active_profile

        if not profile_name:
            raise ValueError("No profile specified and no active profile set")

        profile_path = self.PROFILES_DIR / f"{profile_name}.json"

        if not profile_path.exists():
            raise FileNotFoundError(f"Profile not found: {profile_name}")

        try:
            with open(profile_path) as f:
                data = json.load(f)

            return Profile.from_dict(data)

        except Exception as e:
            raise ValueError(f"Could not load profile {profile_name}: {e}") from e

    def save_profile(self, profile: Profile) -> None:
        """Save a profile to its individual file.

        Args:
            profile: Profile to save.
        """
        # Validate profile name
        if not self._is_valid_profile_name(profile.name):
            raise ValueError(
                f"Invalid profile name: {profile.name}. "
                "Name must be alphanumeric with hyphens only, max 64 characters."
            )

        # Update timestamp
        profile.updated_at = datetime.utcnow().isoformat()

        # Ensure profile directory exists
        self.PROFILES_DIR.mkdir(parents=True, exist_ok=True)

        # Save to file
        profile_path = self.PROFILES_DIR / f"{profile.name}.json"

        with open(profile_path, "w") as f:
            json.dump(profile.to_dict(), f, indent=2)

        # Set as active if it's the first profile
        if not self.active_profile and not self.list_profiles():
            self.active_profile = profile.name
            self.save()
        elif not self.active_profile:
            # If no active profile set, set this one
            self.active_profile = profile.name
            self.save()

    def list_profiles(self) -> list[str]:
        """List all available profile names.

        Returns:
            Sorted list of profile names.
        """
        if not self.PROFILES_DIR.exists():
            return []

        return sorted([p.stem for p in self.PROFILES_DIR.glob("*.json")])

    def delete_profile(self, name: str) -> bool:
        """Delete a profile.

        Args:
            name: Name of profile to delete.

        Returns:
            True if deleted, False if profile doesn't exist.
        """
        profile_path = self.PROFILES_DIR / f"{name}.json"

        if not profile_path.exists():
            return False

        profile_path.unlink()

        # Auto-switch if deleting active profile
        if self.active_profile == name:
            remaining_profiles = self.list_profiles()
            if remaining_profiles:
                self.active_profile = remaining_profiles[0]
                print(f"⚠️  Warning: Active profile '{name}' deleted. Switched to '{self.active_profile}'")
            else:
                self.active_profile = None
                print(f"⚠️  Warning: Active profile '{name}' deleted. No profiles remaining.")
            self.save()

        return True

    def set_active_profile(self, name: str) -> bool:
        """Set the active profile.

        Args:
            name: Name of profile to set as active.

        Returns:
            True if set successfully, False if profile doesn't exist.
        """
        profile_path = self.PROFILES_DIR / f"{name}.json"

        if not profile_path.exists():
            return False

        self.active_profile = name
        self.save()
        return True

    def get_profile(self, name: str | None = None) -> Profile | None:
        """Get a profile by name or the active profile (compatibility method).

        Args:
            name: Profile name to load. If None, loads active profile.

        Returns:
            Profile object or None if not found.
        """
        try:
            return self.load_profile(name)
        except (ValueError, FileNotFoundError):
            return None

    @staticmethod
    def _is_valid_profile_name(name: str) -> bool:
        """Validate profile name.

        Args:
            name: Profile name to validate.

        Returns:
            True if valid, False otherwise.
        """
        import re

        if not name or len(name) > 64:
            return False

        # Allow alphanumeric and hyphens only
        return bool(re.match(r"^[a-zA-Z0-9\-]+$", name))

    # Compatibility methods for legacy code
    def add_profile(self, profile: Profile) -> None:
        """Add or update a profile (compatibility method)."""
        self.save_profile(profile)

    @property
    def default_profile(self) -> str | None:
        """Legacy property for backward compatibility."""
        return self.active_profile

    @default_profile.setter
    def default_profile(self, value: str | None) -> None:
        """Legacy property setter for backward compatibility."""
        self.active_profile = value

    def set_default_profile(self, name: str) -> bool:
        """Set the default profile (compatibility method)."""
        return self.set_active_profile(name)

    @property
    def profiles(self) -> dict[str, Profile]:
        """Legacy property to load all profiles (compatibility method).

        WARNING: This loads all profiles into memory. For large numbers of profiles,
        prefer using load_profile() to load individual profiles on demand.
        """
        result = {}
        for profile_name in self.list_profiles():
            try:
                result[profile_name] = self.load_profile(profile_name)
            except Exception:
                pass  # Skip profiles that fail to load
        return result

    def get_aws_config_for_profile(self, profile_name: str | None = None) -> dict[str, Any]:
        """Get AWS configuration for CloudFormation deployment."""
        profile = self.get_profile(profile_name)
        if not profile:
            raise ValueError(f"Profile not found: {profile_name}")

        return {
            "OktaDomain": profile.okta_domain,
            "OktaClientId": profile.okta_client_id,
            "IdentityPoolName": profile.identity_pool_name,
            "AllowedBedrockRegions": ",".join(profile.allowed_bedrock_regions),
            "EnableMonitoring": "true" if profile.monitoring_enabled else "false",
        }
