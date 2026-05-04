# ABOUTME: Unit tests for async package build functionality
# ABOUTME: Tests async build initiation, status checking, and builds listing

"""Tests for async package build functionality."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, mock_open, patch

import pytest
from cleo.testers.command_tester import CommandTester

from claude_code_with_bedrock.cli.commands.builds import BuildsCommand
from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Config, Profile


class TestPackageAsyncBuild:
    """Tests for async package build functionality."""

    @pytest.fixture
    def mock_profile(self):
        """Create a mock profile for testing."""
        return Profile(
            name="test",
            provider_domain="test.auth.us-east-1.amazoncognito.com",
            client_id="test-client-id",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            allowed_bedrock_regions=["us-east-1"],
            enable_codebuild=True,
            monitoring_enabled=False,
        )

    @pytest.fixture
    def mock_config(self, mock_profile):
        """Create a mock config with profile."""
        config = MagicMock(spec=Config)
        config.get_profile.return_value = mock_profile
        config.active_profile = "test"
        return config

    def test_package_status_check_latest_build(self, mock_config):
        """Test checking status of latest build."""
        command = PackageCommand()
        tester = CommandTester(command)

        # Create mock build info file
        build_info = {
            "build_id": "test-pool-windows-build:12345-67890",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "project": "test-pool-windows-build",
            "bucket": "test-bucket",
        }

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch("builtins.open", mock_open(read_data=json.dumps(build_info))):
                with patch("pathlib.Path.exists", return_value=True):
                    with patch("boto3.client") as mock_boto:
                        # Mock CodeBuild client
                        mock_codebuild = MagicMock()
                        mock_boto.return_value = mock_codebuild

                        # Mock build status response
                        mock_codebuild.batch_get_builds.return_value = {
                            "builds": [
                                {
                                    "id": build_info["build_id"],
                                    "buildStatus": "IN_PROGRESS",
                                    "currentPhase": "BUILD",
                                    "startTime": datetime.now(timezone.utc),
                                }
                            ]
                        }

                        # Run status check
                        tester.execute("--status latest")

                        # Verify CodeBuild was called
                        mock_codebuild.batch_get_builds.assert_called_once_with(ids=[build_info["build_id"]])

                        # Verify command completed successfully
                        assert tester.status_code == 0

    def test_package_status_check_specific_build(self, mock_config):
        """Test checking status of specific build ID."""
        command = PackageCommand()
        tester = CommandTester(command)

        build_id = "test-pool-windows-build:specific-12345"

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch("boto3.client") as mock_boto:
                # Mock CodeBuild client
                mock_codebuild = MagicMock()
                mock_boto.return_value = mock_codebuild

                # Mock successful build
                mock_codebuild.batch_get_builds.return_value = {
                    "builds": [{"id": build_id, "buildStatus": "SUCCEEDED", "buildDurationInMinutes": 12}]
                }

                # Run status check
                tester.execute(f"--status {build_id}")

                # Verify CodeBuild was called with specific ID
                mock_codebuild.batch_get_builds.assert_called_once_with(ids=[build_id])

                # Verify command completed successfully
                assert tester.status_code == 0

    def test_package_status_build_failed(self, mock_config):
        """Test status check for failed build."""
        command = PackageCommand()
        tester = CommandTester(command)

        build_id = "test-pool-windows-build:failed-12345"

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch("boto3.client") as mock_boto:
                # Mock CodeBuild client
                mock_codebuild = MagicMock()
                mock_boto.return_value = mock_codebuild

                # Mock failed build
                mock_codebuild.batch_get_builds.return_value = {
                    "builds": [
                        {
                            "id": build_id,
                            "buildStatus": "FAILED",
                            "phases": [{"phaseType": "BUILD", "phaseStatus": "FAILED"}],
                        }
                    ]
                }

                # Run status check
                tester.execute(f"--status {build_id}")

                # Verify command completed (with error status for failed build)
                assert tester.status_code == 0  # Command itself should succeed even if build failed


class TestBuildsCommand:
    """Tests for builds list command (multi-platform)."""

    MOCK_STACK_OUTPUTS = {
        "ProjectName": "test-pool-windows-build",
        "LinuxX64ProjectName": "test-pool-linux-x64-build",
        "LinuxArm64ProjectName": "test-pool-linux-arm64-build",
        "BuildBucket": "test-bucket",
    }

    @pytest.fixture
    def mock_profile(self):
        """Create a mock profile for testing."""
        return Profile(
            name="test",
            provider_domain="test.auth.us-east-1.amazoncognito.com",
            client_id="test-client-id",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            allowed_bedrock_regions=["us-east-1"],
            enable_codebuild=True,
        )

    @pytest.fixture
    def mock_config(self, mock_profile):
        """Create a mock config with profile."""
        config = MagicMock(spec=Config)
        config.get_profile.return_value = mock_profile
        config.active_profile = "test"
        return config

    def test_builds_list_recent_builds(self, mock_config, mock_profile):
        """Test listing recent builds across all platforms."""
        command = BuildsCommand()
        tester = CommandTester(command)

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch(
                "claude_code_with_bedrock.cli.commands.builds.get_stack_outputs",
                return_value=self.MOCK_STACK_OUTPUTS,
            ):
                with patch("boto3.client") as mock_boto:
                    mock_codebuild = MagicMock()
                    mock_boto.return_value = mock_codebuild

                    now = datetime.now(timezone.utc)
                    mock_codebuild.list_builds_for_project.return_value = {
                        "ids": ["test-pool-windows-build:build-1"]
                    }
                    mock_codebuild.batch_get_builds.return_value = {
                        "builds": [
                            {
                                "id": "test-pool-windows-build:build-1",
                                "buildStatus": "SUCCEEDED",
                                "startTime": now,
                                "endTime": now,
                            },
                        ]
                    }

                    tester.execute("")

                    # Called once per platform (3 projects discovered)
                    assert mock_codebuild.list_builds_for_project.call_count == 3
                    assert tester.status_code == 0

    def test_builds_list_with_limit(self, mock_config, mock_profile):
        """Test listing builds with custom limit."""
        command = BuildsCommand()
        tester = CommandTester(command)

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch(
                "claude_code_with_bedrock.cli.commands.builds.get_stack_outputs",
                return_value=self.MOCK_STACK_OUTPUTS,
            ):
                with patch("boto3.client") as mock_boto:
                    mock_codebuild = MagicMock()
                    mock_boto.return_value = mock_codebuild

                    build_ids = [f"test-pool-windows-build:build-{i}" for i in range(20)]
                    mock_codebuild.list_builds_for_project.return_value = {"ids": build_ids}
                    mock_codebuild.batch_get_builds.return_value = {"builds": []}

                    tester.execute("--limit 5")

                    # Verify only 5 builds were requested per platform call
                    for call in mock_codebuild.batch_get_builds.call_args_list:
                        assert len(call[1]["ids"]) <= 5

    def test_builds_list_no_builds(self, mock_config, mock_profile):
        """Test listing when no builds exist."""
        command = BuildsCommand()
        tester = CommandTester(command)

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch(
                "claude_code_with_bedrock.cli.commands.builds.get_stack_outputs",
                return_value=self.MOCK_STACK_OUTPUTS,
            ):
                with patch("boto3.client") as mock_boto:
                    mock_codebuild = MagicMock()
                    mock_boto.return_value = mock_codebuild
                    mock_codebuild.list_builds_for_project.return_value = {"ids": []}

                    tester.execute("")

                    assert tester.status_code == 0

    def test_builds_list_no_codebuild_stack(self, mock_config):
        """Test when no CodeBuild stack is deployed."""
        command = BuildsCommand()
        tester = CommandTester(command)

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch(
                "claude_code_with_bedrock.cli.commands.builds.get_stack_outputs",
                side_effect=Exception("Stack not found"),
            ):
                result = tester.execute("")
                assert result == 1

    def test_builds_status_latest_all_succeeded(self, mock_config, mock_profile):
        """Test --status latest when all 3 builds succeeded."""
        command = BuildsCommand()
        tester = CommandTester(command)

        now = datetime.now(timezone.utc)
        build_info = {
            "all_builds": {
                "windows": "test-pool-windows-build:win-123",
                "linux-x64": "test-pool-linux-x64-build:lx64-456",
                "linux-arm64": "test-pool-linux-arm64-build:larm-789",
            }
        }

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch("builtins.open", mock_open(read_data=json.dumps(build_info))):
                with patch("pathlib.Path.exists", return_value=True):
                    with patch("boto3.client") as mock_boto:
                        mock_codebuild = MagicMock()
                        mock_boto.return_value = mock_codebuild

                        mock_codebuild.batch_get_builds.return_value = {
                            "builds": [
                                {
                                    "id": "some-build",
                                    "buildStatus": "SUCCEEDED",
                                    "startTime": now,
                                    "endTime": now,
                                }
                            ]
                        }

                        tester.execute("--status latest")

                        assert mock_codebuild.batch_get_builds.call_count == 3
                        assert tester.status_code == 0

    def test_builds_status_latest_mixed_results(self, mock_config, mock_profile):
        """Test --status latest with mixed build results."""
        command = BuildsCommand()
        tester = CommandTester(command)

        now = datetime.now(timezone.utc)
        build_info = {
            "all_builds": {
                "windows": "test-pool-windows-build:win-123",
                "linux-x64": "test-pool-linux-x64-build:lx64-456",
            }
        }

        responses = [
            {"builds": [{"id": "win", "buildStatus": "SUCCEEDED", "startTime": now, "endTime": now}]},
            {"builds": [{"id": "lx64", "buildStatus": "FAILED", "startTime": now, "endTime": now,
                         "phases": [{"phaseType": "BUILD", "phaseStatus": "FAILED"}]}]},
        ]

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch("builtins.open", mock_open(read_data=json.dumps(build_info))):
                with patch("pathlib.Path.exists", return_value=True):
                    with patch("boto3.client") as mock_boto:
                        mock_codebuild = MagicMock()
                        mock_boto.return_value = mock_codebuild
                        mock_codebuild.batch_get_builds.side_effect = responses

                        tester.execute("--status latest")

                        assert tester.status_code == 0
