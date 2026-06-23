# ABOUTME: Shared AWS utility helpers for CLI commands
# ABOUTME: Extracted from multiple commands to reduce duplication

"""Additional AWS utility helpers."""

import configparser
import logging
import platform
from pathlib import Path


def is_wsl() -> bool:
    """Detect if running under Windows Subsystem for Linux (WSL).

    Checks /proc/version for Microsoft/WSL indicators, which is the
    standard detection method used by most Linux tools.
    """
    if platform.system() != "Linux":
        return False
    try:
        version_info = Path("/proc/version").read_text().lower()
        return "microsoft" in version_info or "wsl" in version_info
    except OSError:
        return False


def is_keyring_available() -> bool:
    """Check if a functional keyring backend is available.

    Returns False under WSL (no keyring backend) or if keyring
    imports fail. Returns True on native Linux with SecretService,
    macOS, or Windows.
    """
    if is_wsl():
        return False
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring

        backend = keyring.get_keyring()
        # keyring falls back to FailKeyring when no backend is available
        if isinstance(backend, FailKeyring):
            return False
        return True
    except Exception:
        return False


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
            "credential-process" in v or "claude-code-with-bedrock" in v or "ccwb" in v for v in section_items.values()
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

    Returns profile.codebuild_region when set (cross-region builds),
    otherwise profile.aws_region. Single point of change for all
    CodeBuild client/stack/bucket lookups.

    Co-authored-by: peepeepopapapeepeepo (from PR #330)
    """
    return getattr(profile, "codebuild_region", None) or profile.aws_region


# Regions where CodeBuild offers the Windows Server 2022 container fleet.
# CodeBuild is build-only tooling (not user-facing, not latency-sensitive), so
# deploying it cross-region from the main infrastructure is acceptable.
CODEBUILD_WINDOWS_REGIONS = (
    "us-east-1",
    "us-east-2",
    "us-west-2",
    "eu-central-1",
    "eu-west-1",
    "ap-northeast-1",
    "ap-southeast-2",
    "sa-east-1",
)


def find_nearest_codebuild_region(region: str) -> str:
    """Find the supported Windows-CodeBuild region geographically closest to ``region``.

    Matches on the AWS geography prefix (the continent token, e.g. ``ap``/``eu``/``us``,
    then the finer ``ap-southeast`` grouping) and picks the supported region with the
    longest matching prefix: ``ap-southeast-1`` -> ``ap-southeast-2``,
    ``eu-south-1`` -> ``eu-central-1``, ``us-west-1`` -> ``us-west-2``. Falls back to
    ``us-east-1`` when no supported region shares the continent (e.g. ``af-south-1``,
    ``me-central-1``). Heuristic, not true distance, but keeps builds in-continent
    wherever a supported region exists.
    """
    if region in CODEBUILD_WINDOWS_REGIONS:
        return region

    continent = region.split("-", 1)[0]  # "ap", "eu", "us", "af", ...

    def group_match_len(candidate: str) -> int:
        # Only count a match within the same continent; compare token-by-token
        # ("ap","southeast","1") so "af" never matches "ap".
        if candidate.split("-", 1)[0] != continent:
            return 0
        n = 0
        for ra, rc in zip(region.split("-"), candidate.split("-"), strict=False):
            if ra != rc:
                break
            n += 1
        return n

    best = max(CODEBUILD_WINDOWS_REGIONS, key=group_match_len)
    return best if group_match_len(best) > 0 else "us-east-1"
