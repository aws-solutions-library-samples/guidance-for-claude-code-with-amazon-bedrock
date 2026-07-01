# ABOUTME: Regression test — profile.tags must be passed to CloudFormation deploy_stack
# ABOUTME: Catches the bug where tags were collected by init but silently dropped during deploy

"""Verify that deploy passes profile.tags through to CloudFormationManager.deploy_stack()."""

from unittest.mock import MagicMock, patch

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile


def _make_profile(**overrides):
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(Profile)}
    defaults = {
        "name": "TestProfile",
        "provider_domain": "company.okta.com",
        "client_id": "test-client-id",
        "credential_storage": "session",
        "aws_region": "us-east-1",
        "identity_pool_name": "claude-code-test",
        "sso_enabled": True,
        "provider_type": "okta",
        "monitoring_enabled": False,
        "quota_monitoring_enabled": False,
        "federation_type": "direct",
        "federated_role_arn": "arn:aws:iam::123456789012:role/BedrockRole",
    }
    defaults.update(overrides)
    return Profile(**{k: v for k, v in defaults.items() if k in field_names})


class TestDeployPassesTags:
    """Tags configured in the profile must reach CloudFormationManager.deploy_stack()."""

    @patch("claude_code_with_bedrock.cli.commands.deploy.CloudFormationManager")
    def test_tags_passed_to_deploy_stack(self, MockCFManager):
        """deploy_stack receives profile.tags when tags are configured."""
        tags = {"Environment": "production", "CostCenter": "12345"}
        profile = _make_profile(tags=tags)

        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.outputs = {}
        mock_manager.deploy_stack.return_value = mock_result
        MockCFManager.return_value = mock_manager

        command = DeployCommand()
        console = MagicMock()
        console.print = MagicMock()

        command._deploy_stack("auth", profile, console, mock_manager)

        call_kwargs = mock_manager.deploy_stack.call_args
        assert call_kwargs is not None, "deploy_stack was never called"
        assert call_kwargs.kwargs.get("tags") == tags or call_kwargs[1].get("tags") == tags

    @patch("claude_code_with_bedrock.cli.commands.deploy.CloudFormationManager")
    def test_no_tags_when_profile_has_none(self, MockCFManager):
        """deploy_stack receives tags=None when profile has no tags."""
        profile = _make_profile(tags={})

        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.outputs = {}
        mock_manager.deploy_stack.return_value = mock_result
        MockCFManager.return_value = mock_manager

        command = DeployCommand()
        console = MagicMock()
        console.print = MagicMock()

        command._deploy_stack("auth", profile, console, mock_manager)

        call_kwargs = mock_manager.deploy_stack.call_args
        assert call_kwargs is not None, "deploy_stack was never called"
        passed_tags = call_kwargs.kwargs.get("tags") if call_kwargs.kwargs else call_kwargs[1].get("tags", "MISSING")
        assert passed_tags is None, f"Expected None for empty tags, got {passed_tags}"
