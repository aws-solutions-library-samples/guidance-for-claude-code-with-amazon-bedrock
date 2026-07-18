"""Unit tests for the declarative extra_files matcher and validator.

The matcher (`extra_applies_to`) is the highest-risk piece of the feature: it
reconciles three different platform vocabularies (per-OS arch tokens, landing
families, and the all-OS archive). These tests pin the full truth table.
"""

import pytest

from claude_code_with_bedrock.extra_files import (
    VALID_TARGET_TOKENS,
    extra_applies_to,
    extra_applies_to_any,
    normalize_targets,
    validate_extra_files,
)

# Every token used by _create_per_os_archives (PLATFORM_FILES keys).
PER_OS_TOKENS = ["windows", "linux-x64", "linux-arm64", "macos-arm64", "macos-intel"]
# Every token used by _upload_landing_page_packages.
LANDING_TOKENS = ["windows", "linux", "mac"]


class TestNormalizeTargets:
    def test_single_string(self):
        assert normalize_targets("macos") == ["macos"]

    def test_list(self):
        assert normalize_targets(["macos", "LINUX"]) == ["macos", "linux"]

    def test_whitespace_and_case(self):
        assert normalize_targets("  Windows ") == ["windows"]

    def test_invalid_type(self):
        assert normalize_targets(None) == []
        assert normalize_targets(42) == []


class TestExtraAppliesToAll:
    @pytest.mark.parametrize("platform", PER_OS_TOKENS + LANDING_TOKENS)
    def test_all_matches_every_platform(self, platform):
        assert extra_applies_to("all", platform) is True

    @pytest.mark.parametrize("platform", PER_OS_TOKENS + LANDING_TOKENS)
    def test_all_in_list_matches(self, platform):
        assert extra_applies_to(["all", "windows"], platform) is True


class TestExtraAppliesToExact:
    @pytest.mark.parametrize("token", PER_OS_TOKENS)
    def test_exact_per_os(self, token):
        assert extra_applies_to(token, token) is True

    def test_windows_exact(self):
        assert extra_applies_to("windows", "windows") is True


class TestExtraAppliesToFamily:
    def test_macos_family_matches_both_arches(self):
        assert extra_applies_to("macos", "macos-arm64") is True
        assert extra_applies_to("macos", "macos-intel") is True

    def test_linux_family_matches_both_arches(self):
        assert extra_applies_to("linux", "linux-x64") is True
        assert extra_applies_to("linux", "linux-arm64") is True

    def test_macos_family_matches_landing_mac(self):
        assert extra_applies_to("macos", "mac") is True

    def test_linux_family_matches_landing_linux(self):
        assert extra_applies_to("linux", "linux") is True

    def test_family_does_not_cross_families(self):
        assert extra_applies_to("macos", "linux-x64") is False
        assert extra_applies_to("linux", "macos-arm64") is False
        assert extra_applies_to("macos", "windows") is False


class TestExtraAppliesToArch:
    def test_arch_matches_own_per_os(self):
        assert extra_applies_to("macos-arm64", "macos-arm64") is True

    def test_arch_excludes_sibling_arch_per_os(self):
        # An arch-specific extra must NOT land in the sibling arch's per-os zip.
        assert extra_applies_to("macos-arm64", "macos-intel") is False
        assert extra_applies_to("linux-x64", "linux-arm64") is False

    def test_arch_matches_landing_family(self):
        # Landing families have no arch split, so an arch extra must appear there.
        assert extra_applies_to("macos-arm64", "mac") is True
        assert extra_applies_to("linux-arm64", "linux") is True

    def test_arch_excludes_wrong_landing_family(self):
        assert extra_applies_to("macos-arm64", "windows") is False
        assert extra_applies_to("linux-x64", "mac") is False


class TestExtraAppliesToList:
    def test_list_of_families(self):
        targets = ["macos", "linux"]
        assert extra_applies_to(targets, "macos-arm64") is True
        assert extra_applies_to(targets, "linux-x64") is True
        assert extra_applies_to(targets, "windows") is False
        assert extra_applies_to(targets, "mac") is True

    def test_empty_targets_matches_nothing(self):
        assert extra_applies_to([], "windows") is False


class TestExtraAppliesToAny:
    """Matcher used by ``package`` to filter extras against --target-platform.

    Regression: a windows-only extra must not land in a macos-only build."""

    def test_windows_extra_excluded_from_macos_build(self):
        assert extra_applies_to_any("windows", ["macos-arm64"]) is False
        assert extra_applies_to_any(["windows"], ["macos-arm64", "macos-intel"]) is False

    def test_all_matches_any_build(self):
        assert extra_applies_to_any("all", ["macos-arm64"]) is True
        assert extra_applies_to_any("all", ["windows"]) is True

    def test_family_target_matches_arch_build(self):
        assert extra_applies_to_any("macos", ["macos-arm64"]) is True
        assert extra_applies_to_any(["macos", "macos-arm64", "macos-intel"], ["macos-arm64"]) is True

    def test_arch_target_matches_generic_family_build(self):
        # The non-Go build path can produce generic "macos"/"linux" tokens;
        # arch-targeted extras must still ship in those builds.
        assert extra_applies_to_any("macos-arm64", ["macos"]) is True
        assert extra_applies_to_any("linux-arm64", ["linux"]) is True

    def test_arch_target_excluded_from_sibling_arch_build(self):
        assert extra_applies_to_any("macos-intel", ["macos-arm64"]) is False

    def test_matches_when_any_platform_applies(self):
        assert extra_applies_to_any("windows", ["macos-arm64", "windows"]) is True

    def test_empty_platforms_matches_nothing(self):
        assert extra_applies_to_any("all", []) is False
        assert extra_applies_to_any("all", None) is False


class TestValidateExtraFiles:
    def test_empty_is_valid(self):
        assert validate_extra_files([]) == []
        assert validate_extra_files(None) == []

    def test_valid_entries(self):
        entries = [
            {"name": "certs", "targets": "all", "from": "~/secure/certs"},
            {"name": "preinstall-mac.sh", "targets": ["macos"], "from": "~/x/pre.sh"},
        ]
        assert validate_extra_files(entries) == []

    def test_not_a_list(self):
        assert validate_extra_files({"name": "x"}) != []

    def test_entry_not_a_dict(self):
        errors = validate_extra_files(["nope"])
        assert any("must be an object" in e for e in errors)

    def test_missing_keys(self):
        errors = validate_extra_files([{"name": "x"}])
        assert any("missing key" in e for e in errors)

    def test_unexpected_key(self):
        errors = validate_extra_files([{"name": "x", "targets": "all", "from": "~/x", "mode": "755"}])
        assert any("unexpected key" in e for e in errors)

    def test_unknown_target_token(self):
        errors = validate_extra_files([{"name": "x", "targets": "solaris", "from": "~/x"}])
        assert any("unknown target" in e for e in errors)

    def test_empty_from(self):
        errors = validate_extra_files([{"name": "x", "targets": "all", "from": ""}])
        assert any("'from'" in e for e in errors)

    @pytest.mark.parametrize(
        "bad_name",
        ["../escape", "/etc/passwd", "C:\\Windows\\x", "a/../../b", "sub\\..\\evil"],
    )
    def test_zip_slip_names_rejected(self, bad_name):
        errors = validate_extra_files([{"name": bad_name, "targets": "all", "from": "~/x"}])
        assert errors, f"expected {bad_name!r} to be rejected"

    @pytest.mark.parametrize(
        "reserved",
        ["config.json", "install.sh", "install.bat", "README.md", "collector-config.yaml"],
    )
    def test_reserved_name_collision(self, reserved):
        errors = validate_extra_files([{"name": reserved, "targets": "all", "from": "~/x"}])
        assert any("collides" in e for e in errors)

    def test_reserved_dir_collision(self):
        errors = validate_extra_files([{"name": "claude-settings/foo.json", "targets": "all", "from": "~/x"}])
        assert any("collides" in e for e in errors)

    def test_reserved_binary_prefix_collision(self):
        errors = validate_extra_files([{"name": "credential-process-macos-arm64", "targets": "all", "from": "~/x"}])
        assert any("collides" in e for e in errors)

    def test_nested_name_allowed(self):
        # A safe nested path that does not collide is fine.
        assert validate_extra_files([{"name": "certs/ca.pem", "targets": "all", "from": "~/x"}]) == []


class TestTokenSet:
    def test_valid_tokens_are_stable(self):
        # Guards against accidental token-set drift.
        assert VALID_TARGET_TOKENS == {
            "all",
            "macos",
            "linux",
            "windows",
            "macos-arm64",
            "macos-intel",
            "linux-x64",
            "linux-arm64",
        }
