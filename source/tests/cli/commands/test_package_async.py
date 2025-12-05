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
    """Tests for builds list command."""

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
        """Test listing recent builds."""
        command = BuildsCommand()
        tester = CommandTester(command)

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch("boto3.client") as mock_boto:
                # Mock CodeBuild client
                mock_codebuild = MagicMock()
                mock_boto.return_value = mock_codebuild

                # Mock list builds response
                mock_codebuild.list_builds_for_project.return_value = {
                    "ids": [
                        "test-pool-windows-build:build-1",
                        "test-pool-windows-build:build-2",
                        "test-pool-windows-build:build-3",
                    ]
                }

                # Mock batch get builds response
                now = datetime.now(timezone.utc)
                mock_codebuild.batch_get_builds.return_value = {
                    "builds": [
                        {
                            "id": "test-pool-windows-build:build-1",
                            "buildStatus": "SUCCEEDED",
                            "startTime": now,
                            "endTime": now,
                            "currentPhase": "COMPLETED",
                        },
                        {
                            "id": "test-pool-windows-build:build-2",
                            "buildStatus": "IN_PROGRESS",
                            "startTime": now,
                            "currentPhase": "BUILD",
                        },
                        {
                            "id": "test-pool-windows-build:build-3",
                            "buildStatus": "FAILED",
                            "startTime": now,
                            "endTime": now,
                            "currentPhase": "COMPLETED",
                        },
                    ]
                }

                # Run command
                tester.execute("")

                # Verify CodeBuild was called
                mock_codebuild.list_builds_for_project.assert_called_once_with(
                    projectName="test-pool-windows-build", sortOrder="DESCENDING"
                )

                # Verify command completed successfully
                assert tester.status_code == 0

    def test_builds_list_with_limit(self, mock_config, mock_profile):
        """Test listing builds with custom limit."""
        command = BuildsCommand()
        tester = CommandTester(command)

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch("boto3.client") as mock_boto:
                # Mock CodeBuild client
                mock_codebuild = MagicMock()
                mock_boto.return_value = mock_codebuild

                # Mock responses
                build_ids = [f"test-pool-windows-build:build-{i}" for i in range(20)]
                mock_codebuild.list_builds_for_project.return_value = {"ids": build_ids}
                mock_codebuild.batch_get_builds.return_value = {"builds": []}

                # Run command with limit
                tester.execute("--limit 5")

                # Verify only 5 builds were requested
                called_ids = mock_codebuild.batch_get_builds.call_args[1]["ids"]
                assert len(called_ids) == 5

    def test_builds_list_no_builds(self, mock_config, mock_profile):
        """Test listing when no builds exist."""
        command = BuildsCommand()
        tester = CommandTester(command)

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch("boto3.client") as mock_boto:
                # Mock CodeBuild client with no builds
                mock_codebuild = MagicMock()
                mock_boto.return_value = mock_codebuild
                mock_codebuild.list_builds_for_project.return_value = {"ids": []}

                # Run command
                tester.execute("")

                # Verify command completed successfully
                assert tester.status_code == 0

    def test_builds_list_error_handling(self, mock_config):
        """Test error handling in builds list."""
        command = BuildsCommand()
        tester = CommandTester(command)

        with patch("claude_code_with_bedrock.config.Config.load", return_value=mock_config):
            with patch("boto3.client") as mock_boto:
                # Mock CodeBuild client that raises error
                mock_boto.side_effect = Exception("AWS connection failed")

                # Run command - should handle error gracefully
                result = tester.execute("")

                # Verify error handling - command should fail
                assert result == 1
