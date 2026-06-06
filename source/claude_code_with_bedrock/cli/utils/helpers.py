# ABOUTME: Shared AWS utility helpers for CLI commands
# ABOUTME: Extracted from multiple commands to reduce duplication

"""Additional AWS utility helpers."""

import configparser
import logging
from pathlib import Path


def clear_cached_credentials(profile_name: str) -> bool:
    """Clear cached AWS credentials created by this tool for a profile.

    Only removes the credentials section if it was created by ccwb
    (contains credential_process referencing claude-code-with-bedrock or ccwb).

    Returns True if credentials were cleared, False otherwise.

    Co-authored-by: peepeepopapapeepeepo (from PR #330)
    """
    try:
        cred_path = Path.home() / ".aws" / "credentials"
        if not cred_path.exists():
            return False

        config = configparser.ConfigParser()
        config.read(cred_path, encoding="utf-8")

        if profile_name not in config:
            return False

        # Only remove if it's a section created by this tool
        section_items = dict(config.items(profile_name))
        is_ours = any(
            "credential-process" in v or "claude-code-with-bedrock" in v or "ccwb" in v
            for v in section_items.values()
        )
        if not is_ours:
            return False

        config.remove_section(profile_name)
        with open(cred_path, "w", encoding="utf-8") as f:
            config.write(f)
        return True
    except Exception as e:
        logging.debug(f"Could not clear cached credentials for {profile_name}: {e}")
        return False


def get_codebuild_region(profile) -> str:
    """Get the region where CodeBuild resources are deployed.

    Currently returns profile.aws_region. Extracted as a helper so
    future cross-region CodeBuild support has a single point of change.

    Co-authored-by: peepeepopapapeepeepo (from PR #330)
    """
    return getattr(profile, "codebuild_region", None) or profile.aws_region
