# ABOUTME: Centralized model configuration for Claude models and cross-region inference
# ABOUTME: Single source of truth for model IDs, regions, and descriptions

"""
Centralized configuration for Claude models and cross-region inference profiles.

This module defines all available Claude models, their supported regions,
and cross-region inference configurations in one place for easy maintenance.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

# Default regions for AWS profile based on cross-region profile
DEFAULT_REGIONS = {"us": "us-east-1", "europe": "eu-west-3", "apac": "ap-northeast-1", "us-gov": "us-gov-west-1"}

# Claude model configurations
# Each model defines its availability across different cross-region profiles
CLAUDE_MODELS = {
    "opus-4-1": {
        "name": "Claude Opus 4.1",
        "base_model_id": "anthropic.claude-opus-4-1-20250805-v1:0",
        "profiles": {
            "us": {
                "model_id": "us.anthropic.claude-opus-4-1-20250805-v1:0",
                "description": "US regions only",
                "source_regions": ["us-west-2", "us-east-2", "us-east-1"],
                "destination_regions": ["us-east-1", "us-east-2", "us-west-2"],
            }
        },
    },
    "opus-4": {
        "name": "Claude Opus 4",
        "base_model_id": "anthropic.claude-opus-4-20250514-v1:0",
        "profiles": {
            "us": {
                "model_id": "us.anthropic.claude-opus-4-20250514-v1:0",
                "description": "US regions only",
                "source_regions": [
                    "us-west-2",
                    "us-east-2",
                    "us-east-1",
                ],
                "destination_regions": [
                    "us-west-2",
                    "us-east-2",
                    "us-east-1",
                ],
            }
        },
    },
    "sonnet-4": {
        "name": "Claude Sonnet 4",
        "base_model_id": "anthropic.claude-sonnet-4-20250514-v1:0",
        "profiles": {
            "us": {
                "model_id": "us.anthropic.claude-sonnet-4-20250514-v1:0",
                "description": "US regions",
                "source_regions": [
                    "us-west-2",
                    "us-east-2",
                    "us-east-1",
                ],
                "destination_regions": [
                    "us-west-2",
                    "us-east-2",
                    "us-east-1",
                ],
            },
            "europe": {
                "model_id": "eu.anthropic.claude-sonnet-4-20250514-v1:0",
                "description": "European regions",
                "source_regions": [
                    "eu-west-3",
                    "eu-west-1",
                    "eu-south-2",
                    "eu-south-1",
                    "eu-north-1",
                    "eu-central-1",
                ],
                "destination_regions": [
                    "eu-central-1",
                    "eu-north-1",
                    "eu-south-1",
                    "eu-south-2",
                    "eu-west-1",
                    "eu-west-3",
                ],
            },
            "apac": {
                "model_id": "apac.anthropic.claude-sonnet-4-20250514-v1:0",
                "description": "Asia-Pacific regions",
                "source_regions": [
                    "ap-southeast-2",
                    "ap-southeast-1",
                    "ap-south-2",
                    "ap-south-1",
                    "ap-northeast-3",
                    "ap-northeast-2",
                    "ap-northeast-1",
                ],
                "destination_regions": [
                    "ap-northeast-1",
                    "ap-northeast-2",
                    "ap-northeast-3",
                    "ap-south-1",
                    "ap-south-2",
                    "ap-southeast-1",
                    "ap-southeast-2",
                    "ap-southeast-4",
                ],
            },
            "global": {
                "model_id": "global.anthropic.claude-sonnet-4-20250514-v1:0",
                "description": "Global routing across all AWS regions",
                "source_regions": [
                    "us-east-1",
                    "us-east-2",
                    "us-west-1",
                    "us-west-2",
                    "eu-west-1",
                    "eu-west-3",
                    "eu-central-1",
                    "eu-north-1",
                    "eu-south-1",
                    "eu-south-2",
                    "ap-northeast-1",
                    "ap-northeast-2",
                    "ap-northeast-3",
                    "ap-south-1",
                    "ap-south-2",
                    "ap-southeast-1",
                    "ap-southeast-2",
                    "ap-southeast-4",
                ],
                "destination_regions": [
                    "us-east-1",
                    "us-east-2",
                    "us-west-1",
                    "us-west-2",
                    "eu-west-1",
                    "eu-west-3",
                    "eu-central-1",
                    "eu-north-1",
                    "eu-south-1",
                    "eu-south-2",
                    "ap-northeast-1",
                    "ap-northeast-2",
                    "ap-northeast-3",
                    "ap-south-1",
                    "ap-south-2",
                    "ap-southeast-1",
                    "ap-southeast-2",
                    "ap-southeast-4",
                ],
            },
        },
    },
    "sonnet-4-5": {
        "name": "Claude Sonnet 4.5",
        "base_model_id": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        "profiles": {
            "us": {
                "model_id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "description": "US CRIS - US East (N. Virginia), US East (Ohio), US West (Oregon), US \
                West (N. California)",
                "source_regions": [
                    "us-east-1",  # N. Virginia
                    "us-east-2",  # Ohio
                    "us-west-2",  # Oregon
                    "us-west-1",  # N. California
                ],
                "destination_regions": [
                    "us-east-1",
                    "us-east-2",
                    "us-west-2",
                    "us-west-1",
                ],
            },
            "eu": {
                "model_id": "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "description": "EU CRIS - Europe (Frankfurt, Zurich, Stockholm, Ireland, London, Paris, Milan, Spain)",
                "source_regions": [
                    "eu-central-1",  # Frankfurt
                    "eu-central-2",  # Zurich
                    "eu-north-1",  # Stockholm
                    "eu-west-1",  # Ireland
                    "eu-west-2",  # London
                    "eu-west-3",  # Paris
                    "eu-south-2",  # Milan
                    "eu-south-3",  # Spain
                ],
                "destination_regions": [
                    "eu-central-1",
                    "eu-central-2",
                    "eu-north-1",
                    "eu-west-1",
                    "eu-west-2",
                    "eu-west-3",
                    "eu-south-2",
                    "eu-south-3",
                ],
            },
            "japan": {
                "model_id": "jp.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "description": "Japan CRIS - Asia Pacific (Tokyo), Asia Pacific (Osaka)",
                "source_regions": [
                    "ap-northeast-1",  # Tokyo
                    "ap-northeast-3",  # Osaka
                ],
                "destination_regions": [
                    "ap-northeast-1",
                    "ap-northeast-3",
                ],
            },
            "global": {
                "model_id": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "description": "Global CRIS - All regions worldwide",
                "source_regions": [
                    # North America
                    "us-east-1",  # N. Virginia
                    "us-east-2",  # Ohio
                    "us-west-2",  # Oregon
                    "us-west-1",  # N. California
                    "ca-central-1",  # Canada Central
                    # Europe
                    "eu-central-1",  # Frankfurt
                    "eu-central-2",  # Zurich
                    "eu-north-1",  # Stockholm
                    "eu-west-1",  # Ireland
                    "eu-west-2",  # London
                    "eu-west-3",  # Paris
                    "eu-south-2",  # Milan
                    "eu-south-3",  # Spain
                    # Asia Pacific
                    "ap-southeast-3",  # Jakarta
                    "ap-northeast-1",  # Tokyo
                    "ap-northeast-2",  # Seoul
                    "ap-northeast-3",  # Osaka
                    "ap-south-1",  # Mumbai
                    "ap-south-5",  # Hyderabad
                    "ap-southeast-1",  # Singapore
                    "ap-southeast-4",  # Melbourne
                    "ap-southeast-2",  # Sydney
                    # South America
                    "sa-east-1",  # São Paulo
                ],
                "destination_regions": [
                    # North America
                    "us-east-1",
                    "us-east-2",
                    "us-west-2",
                    "us-west-1",
                    "ca-central-1",
                    # Europe
                    "eu-central-1",
                    "eu-central-2",
                    "eu-north-1",
                    "eu-west-1",
                    "eu-west-2",
                    "eu-west-3",
                    "eu-south-2",
                    "eu-south-3",
                    # Asia Pacific
                    "ap-southeast-3",
                    "ap-northeast-1",
                    "ap-northeast-2",
                    "ap-northeast-3",
                    "ap-south-1",
                    "ap-south-5",
                    "ap-southeast-1",
                    "ap-southeast-4",
                    "ap-southeast-2",
                    # South America
                    "sa-east-1",
                ],
            },
        },
    },
    "sonnet-4-5-govcloud": {
        "name": "Claude Sonnet 4.5 (GovCloud)",
        "base_model_id": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        "profiles": {
            "us-gov": {
                "model_id": "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "description": "US GovCloud regions",
                "source_regions": ["us-gov-west-1", "us-gov-east-1"],
                "destination_regions": ["us-gov-west-1", "us-gov-east-1"],
            },
        },
    },
    "sonnet-3-7": {
        "name": "Claude 3.7 Sonnet",
        "base_model_id": "anthropic.claude-3-7-sonnet-20250219-v1:0",
        "profiles": {
            "us": {
                "model_id": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                "description": "US regions",
                "source_regions": [
                    "us-west-2",
                    "us-east-2",
                    "us-east-1",
                ],
                "destination_regions": [
                    "us-west-2",
                    "us-east-2",
                    "us-east-1",
                ],
            },
            "europe": {
                "model_id": "eu.anthropic.claude-3-7-sonnet-20250219-v1:0",
                "description": "European regions",
                "source_regions": [
                    "eu-west-3",
                    "eu-west-1",
                    "eu-north-1",
                ],
                "destination_regions": [
                    "eu-central-1",
                    "eu-north-1",
                    "eu-west-1",
                    "eu-west-3",
                ],
            },
            "apac": {
                "model_id": "apac.anthropic.claude-3-7-sonnet-20250219-v1:0",
                "description": "Asia-Pacific regions",
                "source_regions": [
                    "ap-southeast-2",
                    "ap-southeast-1",
                    "ap-south-2",
                    "ap-south-1",
                    "ap-northeast-3",
                    "ap-northeast-2",
                    "ap-northeast-1",
                ],
                "destination_regions": [
                    "ap-northeast-1",
                    "ap-northeast-2",
                    "ap-northeast-3",
                    "ap-south-1",
                    "ap-south-2",
                    "ap-southeast-1",
                    "ap-southeast-2",
                    "ap-southeast-4",
                ],
            },
        },
    },
    "sonnet-3-7-govcloud": {
        "name": "Claude 3.7 Sonnet (GovCloud)",
        "base_model_id": "anthropic.claude-3-7-sonnet-20250219-v1:0",
        "profiles": {
            "us-gov": {
                "model_id": "us-gov.anthropic.claude-3-7-sonnet-20250219-v1:0",
                "description": "US GovCloud regions",
                "source_regions": ["us-gov-west-1", "us-gov-east-1"],
                "destination_regions": ["us-gov-west-1", "us-gov-east-1"],
            },
        },
    },
}


def get_available_profiles_for_model(model_key: str) -> list[str]:
    """Get list of available cross-region profiles for a given model."""
    if model_key not in CLAUDE_MODELS:
        return []
    return list(CLAUDE_MODELS[model_key]["profiles"].keys())


def get_model_id_for_profile(model_key: str, profile_key: str) -> str:
    """Get the model ID for a specific model and cross-region profile."""
    if model_key not in CLAUDE_MODELS:
        raise ValueError(f"Unknown model: {model_key}")

    model_config = CLAUDE_MODELS[model_key]
    if profile_key not in model_config["profiles"]:
        raise ValueError(f"Model {model_key} not available in profile {profile_key}")

    return model_config["profiles"][profile_key]["model_id"]


def get_default_region_for_profile(profile_key: str) -> str:
    """Get the default AWS region for a cross-region profile."""
    if profile_key not in DEFAULT_REGIONS:
        raise ValueError(f"Unknown profile: {profile_key}")

    return DEFAULT_REGIONS[profile_key]


def get_source_regions_for_model_profile(model_key: str, profile_key: str) -> list[str]:
    """Get source regions for a specific model and profile combination."""
    if model_key not in CLAUDE_MODELS:
        raise ValueError(f"Unknown model: {model_key}")

    model_config = CLAUDE_MODELS[model_key]
    if profile_key not in model_config["profiles"]:
        raise ValueError(f"Model {model_key} not available in profile {profile_key}")

    return model_config["profiles"][profile_key]["source_regions"]


def get_destination_regions_for_model_profile(model_key: str, profile_key: str) -> list[str]:
    """Get destination regions for a specific model and profile combination."""
    if model_key not in CLAUDE_MODELS:
        raise ValueError(f"Unknown model: {model_key}")

    model_config = CLAUDE_MODELS[model_key]
    if profile_key not in model_config["profiles"]:
        raise ValueError(f"Model {model_key} not available in profile {profile_key}")

    return model_config["profiles"][profile_key]["destination_regions"]


def get_all_model_display_names() -> dict[str, str]:
    """Get a mapping of all model IDs to their display names for UI purposes."""
    display_names = {}

    for _model_key, model_config in CLAUDE_MODELS.items():
        for profile_key, profile_config in model_config["profiles"].items():
            model_id = profile_config["model_id"]
            base_name = model_config["name"]

            if profile_key == "us":
                display_names[model_id] = base_name
            else:
                profile_suffix = profile_key.upper()
                display_names[model_id] = f"{base_name} ({profile_suffix})"

    return display_names


def get_profile_description(model_key: str, profile_key: str) -> str:
    """Get the description for a specific model profile combination."""
    if model_key not in CLAUDE_MODELS:
        raise ValueError(f"Unknown model: {model_key}")

    model_config = CLAUDE_MODELS[model_key]
    if profile_key not in model_config["profiles"]:
        raise ValueError(f"Model {model_key} not available in profile {profile_key}")

    return model_config["profiles"][profile_key]["description"]


def get_source_region_for_profile(profile, model_key: str = None, profile_key: str = None) -> str:
    """Get the source region for a profile, with model-specific logic if available."""
    # First priority: Use user-selected source region if available
    selected_source_region = getattr(profile, "selected_source_region", None)
    if selected_source_region:
        return selected_source_region

    # Fallback: Use cross-region profile logic
    cross_region_profile = getattr(profile, "cross_region_profile", "us")
    if cross_region_profile and cross_region_profile != "us":
        try:
            # Use centralized configuration for non-US profiles
            return get_default_region_for_profile(cross_region_profile)
        except ValueError:
            # Fallback if profile not found in centralized config
            return "eu-west-3" if cross_region_profile == "europe" else "ap-northeast-1"
    else:
        # Use infrastructure region for US or default
        return profile.aws_region


# =============================================================================
# Quota Policy Models and Bedrock Pricing
# =============================================================================


class PolicyType(str, Enum):
    """Types of quota policies."""

    USER = "user"
    GROUP = "group"
    DEFAULT = "default"


class EnforcementMode(str, Enum):
    """Enforcement modes for quota policies."""

    ALERT = "alert"  # Send alerts but don't block access
    BLOCK = "block"  # Block access when quota exceeded (Phase 2)


@dataclass
class QuotaPolicy:
    """
    Represents a quota policy for users, groups, or default.

    Policies define token and cost limits with configurable thresholds
    and enforcement modes.
    """

    policy_type: PolicyType
    identifier: str  # email for user, group name for group, "default" for default
    monthly_token_limit: int
    enabled: bool = True

    # Optional limits
    daily_token_limit: int | None = None

    # Thresholds (auto-calculated from monthly_token_limit if not provided)
    warning_threshold_80: int | None = None
    warning_threshold_90: int | None = None

    # Enforcement (Phase 1: alert only, Phase 2: block support)
    enforcement_mode: EnforcementMode = EnforcementMode.ALERT

    # Metadata
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None

    def __post_init__(self) -> None:
        """Auto-calculate thresholds if not provided."""
        if self.warning_threshold_80 is None:
            self.warning_threshold_80 = int(self.monthly_token_limit * 0.8)
        if self.warning_threshold_90 is None:
            self.warning_threshold_90 = int(self.monthly_token_limit * 0.9)

    def to_dynamodb_item(self) -> dict[str, Any]:
        """Convert policy to DynamoDB item format."""
        item = {
            "pk": f"POLICY#{self.policy_type.value}#{self.identifier}",
            "sk": "CURRENT",
            "policy_type": self.policy_type.value,
            "identifier": self.identifier,
            "monthly_token_limit": self.monthly_token_limit,
            "warning_threshold_80": self.warning_threshold_80,
            "warning_threshold_90": self.warning_threshold_90,
            "enforcement_mode": self.enforcement_mode.value,
            "enabled": self.enabled,
        }

        if self.daily_token_limit is not None:
            item["daily_token_limit"] = self.daily_token_limit

        if self.created_at:
            item["created_at"] = self.created_at.isoformat()

        if self.updated_at:
            item["updated_at"] = self.updated_at.isoformat()

        if self.created_by:
            item["created_by"] = self.created_by

        return item

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> "QuotaPolicy":
        """Create policy from DynamoDB item."""
        return cls(
            policy_type=PolicyType(item["policy_type"]),
            identifier=item["identifier"],
            monthly_token_limit=int(item["monthly_token_limit"]),
            daily_token_limit=int(item["daily_token_limit"]) if item.get("daily_token_limit") else None,
            warning_threshold_80=int(item.get("warning_threshold_80", 0)),
            warning_threshold_90=int(item.get("warning_threshold_90", 0)),
            enforcement_mode=EnforcementMode(item.get("enforcement_mode", "alert")),
            enabled=item.get("enabled", True),
            created_at=datetime.fromisoformat(item["created_at"]) if item.get("created_at") else None,
            updated_at=datetime.fromisoformat(item["updated_at"]) if item.get("updated_at") else None,
            created_by=item.get("created_by"),
        )


@dataclass
class UserQuotaUsage:
    """
    Tracks a user's quota usage for monitoring and alerting.

    Enhanced schema for fine-grained quota tracking including daily limits,
    cost tracking, and policy attribution.
    """

    email: str
    month: str  # YYYY-MM format
    total_tokens: int = 0

    # Daily tracking
    daily_tokens: int = 0
    daily_date: str | None = None  # YYYY-MM-DD, resets when day changes

    # Token type breakdown for cost calculation
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0

    # Cost tracking
    estimated_cost: Decimal = field(default_factory=lambda: Decimal("0"))

    # Policy attribution
    applied_policy_type: PolicyType | None = None
    applied_policy_id: str | None = None
    groups: list[str] = field(default_factory=list)

    # Metadata
    last_updated: datetime | None = None

    def to_dynamodb_item(self) -> dict[str, Any]:
        """Convert usage to DynamoDB item format."""
        item = {
            "pk": f"USER#{self.email}",
            "sk": f"MONTH#{self.month}",
            "email": self.email,
            "total_tokens": self.total_tokens,
            "daily_tokens": self.daily_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_tokens": self.cache_tokens,
            "estimated_cost": str(self.estimated_cost),
        }

        if self.daily_date:
            item["daily_date"] = self.daily_date

        if self.applied_policy_type:
            item["applied_policy_type"] = self.applied_policy_type.value

        if self.applied_policy_id:
            item["applied_policy_id"] = self.applied_policy_id

        if self.groups:
            item["groups"] = self.groups

        if self.last_updated:
            item["last_updated"] = self.last_updated.isoformat()

        return item

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> "UserQuotaUsage":
        """Create usage from DynamoDB item."""
        return cls(
            email=item["email"],
            month=item["sk"].replace("MONTH#", ""),
            total_tokens=int(item.get("total_tokens", 0)),
            daily_tokens=int(item.get("daily_tokens", 0)),
            daily_date=item.get("daily_date"),
            input_tokens=int(item.get("input_tokens", 0)),
            output_tokens=int(item.get("output_tokens", 0)),
            cache_tokens=int(item.get("cache_tokens", 0)),
            estimated_cost=Decimal(item.get("estimated_cost", "0")),
            applied_policy_type=PolicyType(item["applied_policy_type"]) if item.get("applied_policy_type") else None,
            applied_policy_id=item.get("applied_policy_id"),
            groups=item.get("groups", []),
            last_updated=datetime.fromisoformat(item["last_updated"]) if item.get("last_updated") else None,
        )
