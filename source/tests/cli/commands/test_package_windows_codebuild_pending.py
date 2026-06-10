# ABOUTME: Regression test for Windows-only ccwb package falsely reporting build failure
# ABOUTME: An async CodeBuild Windows build produces no local binary but is still a success

"""Regression test: a Windows-only package on a non-Windows host must not error.

When packaging only Windows from macOS/Linux with ``enable_codebuild=True``,
``_build_executable("windows")`` starts an asynchronous CodeBuild build and
returns ``None`` (no local binary yet). ``built_executables`` is therefore empty
even though the build was submitted successfully.

Commit 076da39 (#338, the Go rewrite) dropped the ``windows_codebuild_pending``
escape hatch, so the bare ``if not built_executables`` guard fired and the
command printed "Error: No binaries were successfully built." and returned 1 -
even though the CodeBuild build was running fine (confirmed live: the command
errored while ``ccwb builds`` showed the build In Progress). ``main`` still has
the correct guard; this test pins it on ``beta``.
"""

from unittest.mock import MagicMock, patch

import pytest
from cleo.testers.command_tester import CommandTester

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Config, Profile


@pytest.fixture
def mock_profile():
    """Cognito profile with CodeBuild enabled and monitoring off (simplest path)."""
    return Profile(
        name="test",
        provider_domain="test.auth.us-east-1.amazoncognito.com",
        client_id="test-client-id",
        credential_storage="keyring",
        aws_region="us-east-1",
        identity_pool_name="test-pool",
        allowed_bedrock_regions=["us-east-1"],
        enable_codebuild=True,  # Windows builds go to CodeBuild
        monitoring_enabled=False,
        cowork_3p_enabled=False,  # keep the test focused on the build-success guard
    )


@pytest.fixture
def mock_config(mock_profile):
    config = MagicMock(spec=Config)
    config.get_profile.return_value = mock_profile
    config.active_profile = "test"
    return config


def test_windows_only_async_build_is_not_a_failure(mock_config):
    """Windows-only build started in CodeBuild (None binary) must exit 0, not 1.

    ``_build_executable`` returns ``None`` for the async Windows path. The command
    must treat that as success, still generate config/installer, and NOT print
    "No binaries were successfully built".
    """
    command = PackageCommand()
    tester = CommandTester(command)

    with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config), patch(
        "questionary.confirm"
    ) as mock_confirm, patch.object(
        # Simulate the async CodeBuild submission: no local binary produced.
        PackageCommand, "_build_executable", return_value=None
    ), patch.object(
        PackageCommand, "_create_config"
    ), patch.object(
        PackageCommand, "_create_installer"
    ):
        mock_confirm.return_value.ask.return_value = False

        result = tester.execute("--target-platform windows")

    assert result == 0, "Windows-only async CodeBuild build must succeed (exit 0)"
    assert "No binaries were successfully built" not in tester.io.fetch_output()


def test_windows_only_without_codebuild_still_errors(mock_config, mock_profile):
    """Guard sanity: if CodeBuild is disabled and no binary is produced, still error.

    This confirms the fix narrows the success case to genuine async submissions and
    does not blanket-suppress the real "nothing built" failure.
    """
    mock_profile.enable_codebuild = False
    command = PackageCommand()
    tester = CommandTester(command)

    with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config), patch(
        "questionary.confirm"
    ) as mock_confirm, patch.object(
        PackageCommand, "_build_executable", return_value=None
    ):
        mock_confirm.return_value.ask.return_value = False

        result = tester.execute("--target-platform windows")

    assert result == 1, "With CodeBuild disabled and no binary, package must still error"
