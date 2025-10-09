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
    enable_distribution: bool = False  # Enable package distribution features (S3 + presigned URLs)

    # Quota monitoring configuration
    quota_monitoring_enabled: bool = False  # Enable per-user token quota monitoring
    monthly_token_limit: int = 300000000  # Monthly token limit per user (300M default)
    warning_threshold_80: int = 240000000  # Warning threshold at 80% (240M default)
    warning_threshold_90: int = 270000000  # Critical threshold at 90% (270M default)

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

    CONFIG_DIR = Path(__file__).parent.parent / ".ccwb-config"
    CONFIG_FILE = CONFIG_DIR / "config.json"

    def __init__(self):
        """Initialize configuration."""
        self.profiles: dict[str, Profile] = {}
        self.default_profile: str | None = None
        self._ensure_config_dir()

    def _ensure_config_dir(self) -> None:
        """Ensure configuration directory exists."""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from file."""
        config = cls()

        if cls.CONFIG_FILE.exists():
            try:
                with open(cls.CONFIG_FILE) as f:
                    data = json.load(f)

                # Load profiles
                for profile_name, profile_data in data.get("profiles", {}).items():
                    config.profiles[profile_name] = Profile.from_dict(profile_data)

                config.default_profile = data.get("default_profile")

            except Exception as e:
                # If config is corrupted, start fresh
                print(f"Warning: Could not load config: {e}")

        return config

    def save(self) -> None:
        """Save configuration to file."""
        data = {
            "version": "1.0",
            "default_profile": self.default_profile,
            "profiles": {name: profile.to_dict() for name, profile in self.profiles.items()},
        }

        with open(self.CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def add_profile(self, profile: Profile) -> None:
        """Add or update a profile."""
        profile.updated_at = datetime.utcnow().isoformat()
        self.profiles[profile.name] = profile

        # Set as default if it's the first profile
        if len(self.profiles) == 1:
            self.default_profile = profile.name

    def get_profile(self, name: str | None = None) -> Profile | None:
        """Get a profile by name or the default profile."""
        if name:
            return self.profiles.get(name)
        elif self.default_profile:
            return self.profiles.get(self.default_profile)
        return None

    def list_profiles(self) -> list[str]:
        """List all profile names."""
        return list(self.profiles.keys())

    def delete_profile(self, name: str) -> bool:
        """Delete a profile."""
        if name in self.profiles:
            del self.profiles[name]

            # Update default if needed
            if self.default_profile == name:
                self.default_profile = list(self.profiles.keys())[0] if self.profiles else None

            return True
        return False

    def set_default_profile(self, name: str) -> bool:
        """Set the default profile."""
        if name in self.profiles:
            self.default_profile = name
            return True
        return False

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
