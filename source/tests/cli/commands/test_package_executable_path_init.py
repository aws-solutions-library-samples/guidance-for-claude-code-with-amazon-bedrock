# ABOUTME: Regression test for the executable_path UnboundLocalError (PR #320 bug 1)
# ABOUTME: Ensures a build failure before executable_path is assigned doesn't crash package

"""Regression test: package must not raise UnboundLocalError when a build fails early.

PR #320 bug 1: inside the per-platform build loop, ``executable_path`` is assigned by
``_build_executable()``. If that call raises before returning, the subsequent
``if platform_name == "windows" and executable_path is None`` check (reached when
monitoring is enabled) referenced an unbound local and crashed with UnboundLocalError
instead of falling through to the friendly "No binaries were successfully built" path.
"""

from unittest.mock import MagicMock, patch

import pytest
from cleo.testers.command_tester import CommandTester

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Config, Profile


@pytest.fixture
def mock_profile():
    """A cognito profile with monitoring enabled so the loop reaches the OTEL branch."""
    return Profile(
        name="test",
        provider_domain="test.auth.us-east-1.amazoncognito.com",
        client_id="test-client-id",
        credential_storage="keyring",
        aws_region="us-east-1",
        identity_pool_name="test-pool",
        allowed_bedrock_regions=["us-east-1"],
        monitoring_enabled=True,  # reaches the `executable_path is None` OTEL branch
    )


@pytest.fixture
def mock_config(mock_profile):
    config = MagicMock(spec=Config)
    config.get_profile.return_value = mock_profile
    config.active_profile = "test"
    return config


def test_build_failure_before_assignment_does_not_crash(mock_config):
    """A _build_executable failure on the first platform must not raise UnboundLocalError."""
    command = PackageCommand()
    tester = CommandTester(command)

    with (
        patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config),
        patch("questionary.confirm") as mock_confirm,
        patch.object(PackageCommand, "_build_executable", side_effect=RuntimeError("Nuitka not found")),
    ):
        # All confirm() prompts (co-authored-by, customize OTEL) answer No.
        mock_confirm.return_value.ask.return_value = False

        # Build only Windows so the loop's single iteration fails before assignment.
        # Before the fix this raised UnboundLocalError out of handle(); the assertion
        # below is unreachable because tester.execute() would propagate that exception.
        result = tester.execute("--target-platform windows")

    # Reaches the "No binaries were successfully built" guard and exits cleanly (1)
    # instead of crashing with UnboundLocalError.
    assert result == 1
