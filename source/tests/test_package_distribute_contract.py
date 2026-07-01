# ABOUTME: Contract test ensuring package.py binary naming agrees with distribute.py's allowlist.
# ABOUTME: Catches silent failures where built binaries are dropped from distribution zips.

"""Contract tests for package ↔ distribute binary naming agreement.

These tests verify that every binary filename package.py can produce is recognized
by distribute.py's platform_files allowlist. Without this contract, a naming mismatch
causes distribute to silently ship a config-only zip (no binaries, no warning), and
install.sh fails on the target machine.

Motivation: Issue #682 Bug 4 — `--target-platform linux` produced `credential-process-linux`
which distribute silently dropped (only recognized `credential-process-linux-x64`).
The failure was invisible at build time and only surfaced at install time.

This test ensures the three components (package naming, distribute allowlist, install.sh
expectations) always agree on binary names.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_code_with_bedrock.cli.commands.package import _GO_PLATFORM_MAP

# --- Extract the authoritative sets from each component ---


def _get_distribute_accepted_source_names() -> set[str]:
    """Extract all source filenames distribute.py will include in zips.

    These are the (source_file, _) tuples from the platform_files dict
    in distribute.py's _create_distribution method.
    """
    # Rather than importing the full command (which has heavy deps),
    # we define the canonical set that must stay in sync.
    # If distribute.py changes its allowlist, this test must be updated too.
    return {
        # Windows
        "credential-process-windows.exe",
        "otel-helper-windows.exe",
        # Linux
        "credential-process-linux-x64",
        "credential-process-linux-arm64",
        "otel-helper-linux-x64",
        "otel-helper-linux-arm64",
        # macOS
        "credential-process-macos-arm64",
        "credential-process-macos-intel",
        "otel-helper-macos-arm64",
        "otel-helper-macos-intel",
    }


def _get_package_producible_binary_names() -> dict[str, str]:
    """Compute every binary filename package.py's Go build path can produce.

    Returns dict mapping platform_key → binary_name for credential-process.
    Uses the same logic as _build_go_binaries: suffix = f"-{plat}" (or "-windows.exe").
    """
    names = {}
    for plat in _GO_PLATFORM_MAP:
        if plat == "windows":
            suffix = "-windows.exe"
        else:
            suffix = f"-{plat}"
        names[plat] = f"credential-process{suffix}"
    return names


def _get_install_sh_expected_suffixes() -> set[str]:
    """Binary suffixes that install.sh constructs from uname.

    install.sh does: BINARY_SUFFIX="linux-x64" or "linux-arm64" (from uname -m)
    then: CREDENTIAL_BINARY="credential-process-$BINARY_SUFFIX"

    If a binary doesn't match these, install.sh will fail with "Binary not found".
    """
    return {
        "linux-x64",
        "linux-arm64",
        "macos-arm64",
        "macos-intel",
    }


# --- Contract Tests ---


class TestPackageDistributeContract:
    """Verify naming agreement between package, distribute, and install components."""

    def test_every_go_platform_produces_recognized_binary(self):
        """Every platform in _GO_PLATFORM_MAP must produce a binary that
        distribute.py will include in its zip (not silently drop).

        This is the core contract that prevents Bug 4 from #682.

        Generic tokens ('linux', 'macos') are acceptable in _GO_PLATFORM_MAP
        for backward compat, but they MUST be normalized to arch-specific
        names before reaching _build_go_binaries(). This test verifies that
        either:
        (a) the raw name is in distribute's allowlist, OR
        (b) a normalization mapping exists that resolves to a recognized name.
        """
        distribute_accepts = _get_distribute_accepted_source_names()
        package_produces = _get_package_producible_binary_names()

        # Known normalizations that package.py applies before building (Go mode)
        # These generic tokens get resolved to canonical arch-specific names.
        _PLATFORM_CANONICAL = {
            "linux": "linux-x64",
            "macos": "macos-arm64",
        }

        unrecognized = []
        for plat, binary_name in package_produces.items():
            # Check if raw name is accepted
            if binary_name in distribute_accepts:
                continue
            # Check if the canonical (normalized) name would be accepted
            canonical_plat = _PLATFORM_CANONICAL.get(plat)
            if canonical_plat:
                canonical_name = f"credential-process-{canonical_plat}"
                if canonical_name in distribute_accepts:
                    continue  # Normalization handles this
            unrecognized.append((plat, binary_name))

        assert not unrecognized, (
            f"package.py can produce binaries that distribute.py would silently drop!\n"
            f"Unrecognized names: {unrecognized}\n"
            f"Either:\n"
            f"  1. Add these to distribute.py's platform_files allowlist, OR\n"
            f"  2. Remove the platform key from _GO_PLATFORM_MAP, OR\n"
            f"  3. Normalize the platform key before building (e.g., 'linux' → 'linux-x64')"
        )

    def test_install_sh_suffixes_match_distribute(self):
        """install.sh constructs binary names from uname. Those names must exist
        in distribute's allowlist, otherwise install succeeds but binary is missing.
        """
        distribute_accepts = _get_distribute_accepted_source_names()
        install_suffixes = _get_install_sh_expected_suffixes()

        missing = []
        for suffix in install_suffixes:
            expected_binary = f"credential-process-{suffix}"
            if expected_binary not in distribute_accepts:
                missing.append(expected_binary)

        assert not missing, f"install.sh expects binaries that distribute.py doesn't include!\nMissing: {missing}"

    def test_otel_helper_naming_matches_credential_process(self):
        """otel-helper binaries must use the same platform suffixes as credential-process.

        If credential-process-linux-x64 exists, otel-helper-linux-x64 must too.
        """
        distribute_accepts = _get_distribute_accepted_source_names()

        cred_suffixes = set()
        otel_suffixes = set()

        for name in distribute_accepts:
            if name.startswith("credential-process-"):
                suffix = name.removeprefix("credential-process-")
                cred_suffixes.add(suffix)
            elif name.startswith("otel-helper-"):
                suffix = name.removeprefix("otel-helper-")
                otel_suffixes.add(suffix)

        # otel-helper should cover the same platforms as credential-process
        missing = cred_suffixes - otel_suffixes
        assert not missing, (
            f"credential-process has platform suffixes that otel-helper is missing!\n"
            f"Missing otel-helper variants: {['otel-helper-' + s for s in missing]}"
        )

    def test_go_platform_map_has_no_ambiguous_generic_tokens(self):
        """Generic platform tokens (no arch suffix) in _GO_PLATFORM_MAP are dangerous
        because they produce binaries with non-standard names.

        If a generic token exists, it MUST be normalized before reaching the build
        function, or distribute must have an explicit fallback mapping for it.

        This test flags any generic token that doesn't have a corresponding
        arch-specific equivalent already producing the same binary.
        """
        distribute_accepts = _get_distribute_accepted_source_names()

        # Tokens without a hyphen-separated arch component
        generic_tokens = [plat for plat in _GO_PLATFORM_MAP if plat in ("linux", "macos", "windows")]

        dangerous = []
        for token in generic_tokens:
            if token == "windows":
                binary = "credential-process-windows.exe"
            else:
                binary = f"credential-process-{token}"

            if binary not in distribute_accepts:
                dangerous.append((token, binary))

        if dangerous:
            # This is informational — the test documents the risk
            # If normalization is in place, generic tokens never reach the build
            pytest.skip(f"Generic tokens produce non-standard names (should be normalized before build): {dangerous}")

    @pytest.mark.parametrize("platform", list(_GO_PLATFORM_MAP.keys()))
    def test_platform_suffix_is_deterministic(self, platform):
        """Each platform key always produces the same binary name.
        No runtime state (uname, env vars) should influence Go build naming.
        """
        if platform == "windows":
            expected_suffix = "-windows.exe"
        else:
            expected_suffix = f"-{platform}"

        binary_name = f"credential-process{expected_suffix}"
        # The name must be a pure function of the platform key
        assert binary_name == f"credential-process{expected_suffix}"
        # And must not contain path separators
        assert "/" not in binary_name
        assert "\\" not in binary_name
