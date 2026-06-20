# ABOUTME: Tests for utility helper wiring into CLI commands
# ABOUTME: Verifies get_codebuild_region and clear_cached_credentials are properly used

"""Tests verifying utility helpers are wired into commands."""

from pathlib import Path

COMMANDS_DIR = Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands"
HELPER_IMPORT = "from claude_code_with_bedrock.cli.utils.helpers import get_codebuild_region"


class TestGetCodebuildRegionWiring:
    """Verify get_codebuild_region is used in CodeBuild commands.

    All CodeBuild-region resources (the codebuild client, the codebuild stack
    outputs, and the S3 BuildBucket) must resolve through the same region
    helper. Mixing get_codebuild_region() for the client with raw
    profile.aws_region for the bucket/stack would break cross-region builds:
    the client would hit one region while the bucket lookup hit another.
    """

    def test_builds_command_uses_helper(self):
        """builds.py routes the codebuild client through the helper."""
        source = (COMMANDS_DIR / "builds.py").read_text(encoding="utf-8")
        assert HELPER_IMPORT in source
        assert "get_codebuild_region(profile)" in source

    def test_builds_command_has_no_raw_region_for_codebuild(self):
        """builds.py uses no raw profile.aws_region (all codebuild paths use the helper)."""
        source = (COMMANDS_DIR / "builds.py").read_text(encoding="utf-8")
        # Every CodeBuild resource in builds.py (client, stack outputs, bucket)
        # must go through get_codebuild_region; nothing should reach raw aws_region.
        assert "profile.aws_region" not in source

    def test_package_cb_command_uses_helper(self):
        """package_cb.py routes codebuild client, stack outputs, and S3 bucket through the helper."""
        source = (COMMANDS_DIR / "package_cb.py").read_text(encoding="utf-8")
        assert HELPER_IMPORT in source
        # codebuild client + stack outputs + S3 upload bucket all use the helper
        assert source.count("get_codebuild_region(profile)") >= 3

    def test_package_command_uses_helper(self):
        """package.py routes codebuild client, stack outputs, and S3 bucket through the helper."""
        source = (COMMANDS_DIR / "package.py").read_text(encoding="utf-8")
        assert HELPER_IMPORT in source
        # two codebuild clients (status + start), stack outputs, S3 upload, plus the
        # build-status client = all codebuild-region resources use the helper
        assert source.count("get_codebuild_region(profile)") >= 4

    def test_distribute_command_uses_helper(self):
        """distribute.py routes its CodeBuild resources (windows-build clients, codebuild
        stack outputs, BuildBucket download) through the helper. Without this, `ccwb
        distribute` queries the main region for a cross-region build and silently bundles
        no Windows binary."""
        source = (COMMANDS_DIR / "distribute.py").read_text(encoding="utf-8")
        assert HELPER_IMPORT in source
        # 4 windows-build clients + codebuild stack outputs + BuildBucket S3 = 6 sites
        assert source.count("get_codebuild_region(profile)") >= 6
        # The codebuild stack outputs must NOT be read with the main region.
        assert "get_stack_outputs(codebuild_stack_name, profile.aws_region)" not in source

    def test_distribute_windows_build_client_not_main_region(self):
        """The windows-build CodeBuild client must never use profile.aws_region."""
        source = (COMMANDS_DIR / "distribute.py").read_text(encoding="utf-8")
        # the windows-build project is CodeBuild; its client must resolve via the helper
        lines = source.splitlines()
        for i, line in enumerate(lines):
            if "windows-build" in line and "project_name" in line:
                # the next non-blank line creates the codebuild client — must use helper
                nxt = lines[i + 1]
                assert "get_codebuild_region(profile)" in nxt, (
                    f"windows-build client at line {i + 2} must use get_codebuild_region, got: {nxt.strip()}"
                )


class TestClearCachedCredentialsWiring:
    """Verify clear_cached_credentials is used in destroy command."""

    def test_destroy_command_clears_credentials(self):
        """destroy.py calls clear_cached_credentials after successful stack destruction."""
        source = (
            Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands" / "destroy.py"
        ).read_text(encoding="utf-8")
        assert "from claude_code_with_bedrock.cli.utils.helpers import clear_cached_credentials" in source
        assert "clear_cached_credentials(profile_name)" in source

    def test_credential_cleanup_after_stack_destroy(self):
        """Credential cleanup happens after stacks are destroyed, not before."""
        source = (
            Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands" / "destroy.py"
        ).read_text(encoding="utf-8")
        idx_destroy = source.find("stack destroyed")
        idx_clear = source.find("clear_cached_credentials(profile_name)")
        assert idx_destroy < idx_clear, "Credentials should be cleared after stack destruction"
