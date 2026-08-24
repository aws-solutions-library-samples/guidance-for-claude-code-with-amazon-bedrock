# ABOUTME: Regression tests for issue #528 — ExistingOIDCProviderArn parameter passing
# ABOUTME: Verifies the auth stack receives ExistingOIDCProviderArn when profile.existing_oidc_provider_arn is set

"""Deploy existing OIDC provider ARN parameter tests.

Issue #528: When multiple profiles share the same OIDC issuer in one AWS
account, the second profile's auth stack deploy fails with:

    "EntityAlreadyExists: Provider with url ... already exists."

The fix lets the user set profile.existing_oidc_provider_arn to the first
profile's IAM OIDC provider ARN, and passes "ExistingOIDCProviderArn=<arn>"
to the CloudFormation auth stack so it reuses the existing provider instead of
trying to create a duplicate.

These tests verify that _deploy_stack("auth", ...) correctly appends the
ExistingOIDCProviderArn parameter when the profile has it set, and omits it
when not set.
"""

from dataclasses import fields
from unittest.mock import MagicMock

from rich.console import Console

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile


def _base_profile(**overrides):
    """Create a minimal valid profile with overrides.

    Filters overrides to only valid Profile fields to avoid TypeError.
    """
    field_names = {f.name for f in fields(Profile)}
    defaults = {
        "name": "TestProfile",
        "provider_domain": "company.okta.com",
        "client_id": "test-client-id",
        "credential_storage": "session",
        "aws_region": "us-east-1",
        "identity_pool_name": "claude-code-test",
        "sso_enabled": True,
        "provider_type": "okta",
        "monitoring_enabled": True,
        "monitoring_mode": "central",
        "federation_type": "direct",
        "federated_role_arn": "arn:aws:iam::123456789012:role/BedrockRole",
    }
    defaults.update(overrides)
    return Profile(**{k: v for k, v in defaults.items() if k in field_names})


class TestExistingOIDCProviderArn:
    """Tests for ExistingOIDCProviderArn parameter passing in auth stack deploys."""

    def test_existing_oidc_arn_passed_when_set(self):
        """When profile.existing_oidc_provider_arn is set, parameter is passed to CF stack."""
        # Arrange
        provider_arn = "arn:aws:iam::123456789012:oidc-provider/company.okta.com"
        profile = _base_profile(
            provider_type="okta",
            existing_oidc_provider_arn=provider_arn,
        )
        command = DeployCommand()
        console = Console()

        # Mock CloudFormationManager.deploy_stack to capture params
        mock_cf_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.error = None
        mock_cf_manager.deploy_stack.return_value = mock_result

        # Act — invoke _deploy_stack which builds params and calls cf_manager.deploy_stack
        result = command._deploy_stack("auth", profile, console, mock_cf_manager)

        # Assert
        assert result == 0, "Deploy should succeed"
        assert mock_cf_manager.deploy_stack.called, "CF manager deploy_stack should be called"

        # Extract the parameters kwarg passed to deploy_stack
        call_kwargs = mock_cf_manager.deploy_stack.call_args.kwargs
        params = call_kwargs.get("parameters", [])

        # params is a list of {"ParameterKey": ..., "ParameterValue": ...} dicts
        # (after _convert_params_to_boto3 conversion)
        param_dict = {p["ParameterKey"]: p["ParameterValue"] for p in params}

        assert "ExistingOIDCProviderArn" in param_dict, (
            f"ExistingOIDCProviderArn parameter missing. Got params: {list(param_dict.keys())}"
        )
        assert param_dict["ExistingOIDCProviderArn"] == provider_arn, (
            f"ExistingOIDCProviderArn value mismatch. "
            f"Expected {provider_arn}, got {param_dict['ExistingOIDCProviderArn']}"
        )

    def test_existing_oidc_arn_absent_when_none(self):
        """When profile.existing_oidc_provider_arn is None, parameter is NOT passed."""
        # Arrange
        profile = _base_profile(
            provider_type="okta",
            existing_oidc_provider_arn=None,  # Explicitly None (default)
        )
        command = DeployCommand()
        console = Console()

        mock_cf_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.error = None
        mock_cf_manager.deploy_stack.return_value = mock_result

        # Act
        result = command._deploy_stack("auth", profile, console, mock_cf_manager)

        # Assert
        assert result == 0, "Deploy should succeed"
        assert mock_cf_manager.deploy_stack.called, "CF manager deploy_stack should be called"

        call_kwargs = mock_cf_manager.deploy_stack.call_args.kwargs
        params = call_kwargs.get("parameters", [])
        param_dict = {p["ParameterKey"]: p["ParameterValue"] for p in params}

        assert "ExistingOIDCProviderArn" not in param_dict, (
            f"ExistingOIDCProviderArn should NOT be in params when None. Got params: {list(param_dict.keys())}"
        )

    def test_existing_oidc_arn_passed_for_cognito_provider(self):
        """ExistingOIDCProviderArn works for cognito provider type too."""
        # Arrange — Cognito pool ARN format (Cognito User Pool uses cognito-idp issuer)
        provider_arn = (
            "arn:aws:iam::123456789012:oidc-provider/cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool123"
        )
        profile = _base_profile(
            provider_type="cognito",
            cognito_user_pool_id="us-east-1_TestPool123",
            existing_oidc_provider_arn=provider_arn,
        )
        command = DeployCommand()
        console = Console()

        mock_cf_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.error = None
        mock_cf_manager.deploy_stack.return_value = mock_result

        # Act
        result = command._deploy_stack("auth", profile, console, mock_cf_manager)

        # Assert
        assert result == 0, "Deploy should succeed"
        assert mock_cf_manager.deploy_stack.called, "CF manager deploy_stack should be called"

        call_kwargs = mock_cf_manager.deploy_stack.call_args.kwargs
        params = call_kwargs.get("parameters", [])
        param_dict = {p["ParameterKey"]: p["ParameterValue"] for p in params}

        assert "ExistingOIDCProviderArn" in param_dict, (
            f"ExistingOIDCProviderArn parameter missing for Cognito. Got params: {list(param_dict.keys())}"
        )
        assert param_dict["ExistingOIDCProviderArn"] == provider_arn, (
            f"ExistingOIDCProviderArn value mismatch for Cognito. "
            f"Expected {provider_arn}, got {param_dict['ExistingOIDCProviderArn']}"
        )


class TestFederatedRoleNameParam:
    """FederatedRoleName threaded to the auth stack only when profile sets it (issue #528).

    Per-profile role name avoids the same-account IAM role collision. Unset ->
    template default (preserves existing single-profile deploys).
    """

    def _params(self, profile):
        command = DeployCommand()
        console = Console()
        mock_cf = MagicMock()
        mock_cf.deploy_stack.return_value = MagicMock(success=True, error=None)
        assert command._deploy_stack("auth", profile, console, mock_cf) == 0
        params = mock_cf.deploy_stack.call_args.kwargs.get("parameters", [])
        return {p["ParameterKey"]: p["ParameterValue"] for p in params}

    def test_role_name_passed_when_set(self):
        """When federated_role_name is set, FederatedRoleName param is passed."""
        profile = _base_profile(provider_type="okta", federated_role_name="BedrockOktaFederatedRole-wmgccwb2")
        param_dict = self._params(profile)
        assert param_dict.get("FederatedRoleName") == "BedrockOktaFederatedRole-wmgccwb2", (
            f"FederatedRoleName missing/wrong. Got: {list(param_dict.keys())}"
        )

    def test_role_name_absent_when_none(self):
        """When federated_role_name is None, FederatedRoleName is NOT passed (template default)."""
        profile = _base_profile(provider_type="okta", federated_role_name=None)
        param_dict = self._params(profile)
        assert "FederatedRoleName" not in param_dict, (
            f"FederatedRoleName should be absent when None. Got: {list(param_dict.keys())}"
        )
