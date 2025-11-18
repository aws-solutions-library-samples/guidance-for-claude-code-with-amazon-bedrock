# ABOUTME: Centralized model configuration for Claude models and cross-region inference
# ABOUTME: Single source of truth for model IDs, regions, and descriptions

"""
Centralized configuration for Claude models and cross-region inference profiles.

This module defines all available Claude models, their supported regions,
and cross-region inference configurations in one place for easy maintenance.
"""

# Default regions for AWS profile based on cross-region profile
DEFAULT_REGIONS = {"us": "us-east-1", "europe": "eu-west-3", "apac": "ap-northeast-1"}

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
