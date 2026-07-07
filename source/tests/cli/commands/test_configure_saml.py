# ABOUTME: Tests for `ccwb configure-saml` — automates Cognito SAML provider setup for
# ABOUTME: the IAM Identity Center landing page after the manual IDC-side SAML app is created

"""Tests for ConfigureSamlCommand.

Covers:
- Guard: command refuses to run for non-`landing-page-idc` profiles
- Guard: command fails cleanly when deployment info can't be found (no deployment-info.json
  and no CloudFormation stacks)
- Happy path via deployment-info.json: creates the SAML identity provider and enables it on
  both the web app client and the bootstrap client
- Update path: an existing SAML identity provider is updated, not recreated
- Fallback path via CloudFormation stack outputs when deployment-info.json is absent
- Non-fatal handling when no bootstrap client exists (dynamic config simply disabled)

Note: ConfigureSamlCommand builds its own `rich.console.Console()` rather than writing through
cleo's IO, so output assertions use pytest's `capsys` fixture (which captures real stdout)
instead of `tester.io.fetch_output()`.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from cleo.testers.command_tester import CommandTester

from claude_code_with_bedrock.cli.commands.configure_saml import ConfigureSamlCommand
from claude_code_with_bedrock.config import Profile


def _profile(**overrides) -> Profile:
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(Profile)}
    defaults = {
        "name": "TestProfile",
        "provider_domain": "company.okta.com",
        "client_id": "test-client-id",
        "credential_storage": "session",
        "aws_region": "us-east-1",
        "identity_pool_name": "claude-code-test",
        "distribution_type": "landing-page-idc",
    }
    defaults.update(overrides)
    return Profile(**{k: v for k, v in defaults.items() if k in field_names})


def _run(metadata_url="https://portal.sso.us-east-1.amazonaws.com/saml/metadata/xyz", profile_option=None):
    command = ConfigureSamlCommand()
    tester = CommandTester(command)
    args = metadata_url
    if profile_option:
        args = f"{args} --profile {profile_option}"
    tester.execute(args)
    return tester


class TestDistributionTypeGuard:
    """The command must refuse to run for anything other than landing-page-idc."""

    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_rejects_non_idc_distribution_type(self, mock_get_profile, capsys):
        mock_get_profile.return_value = _profile(distribution_type="landing-page")
        tester = _run()
        assert tester.status_code == 1
        assert "landing-page-idc" in capsys.readouterr().out

    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_rejects_none_distribution_type(self, mock_get_profile):
        mock_get_profile.return_value = _profile(distribution_type=None)
        tester = _run()
        assert tester.status_code == 1

    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_no_profile_found(self, mock_get_profile, capsys):
        mock_get_profile.return_value = None
        tester = _run()
        assert tester.status_code == 1
        assert "No profile found" in capsys.readouterr().out


class TestDeploymentInfoResolution:
    """The command locates User Pool / client IDs via deployment-info.json first,
    falling back to CloudFormation stack outputs."""

    @patch("boto3.client")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_missing_deployment_info_and_cfn_failure_is_non_fatal(
        self, mock_get_profile, mock_exists, mock_boto_client, capsys
    ):
        """No deployment-info.json and a CloudFormation lookup error must fail cleanly, not crash."""
        mock_get_profile.return_value = _profile()
        mock_cfn = MagicMock()
        mock_cfn.describe_stacks.side_effect = Exception("Stack does not exist")
        mock_boto_client.return_value = mock_cfn

        tester = _run()
        assert tester.status_code == 1
        assert "deployed the distribution stack first" in capsys.readouterr().out

    @patch("boto3.client")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_incomplete_cfn_outputs_reports_missing_info(self, mock_get_profile, mock_exists, mock_boto_client, capsys):
        """If CFN outputs are missing required keys (e.g. no landing page URL), fail with a clear message."""
        mock_get_profile.return_value = _profile()
        mock_cfn = MagicMock()
        mock_cfn.describe_stacks.side_effect = [
            {
                "Stacks": [
                    {
                        "Outputs": [
                            {"OutputKey": "UserPoolId", "OutputValue": "us-east-1_abc123"},
                            {"OutputKey": "UserPoolClientId", "OutputValue": "clientid123"},
                        ]
                    }
                ]
            },
            {"Stacks": [{"Outputs": []}]},  # landing page stack missing LandingPageUrl
        ]
        mock_boto_client.return_value = mock_cfn

        tester = _run()
        assert tester.status_code == 1
        assert "Missing required deployment information" in capsys.readouterr().out


class TestSamlProviderSetup:
    """Happy-path and update-path coverage for the Cognito SAML identity provider wiring."""

    def _mock_cognito_client(self, *, provider_exists: bool, bootstrap_client=None):
        client = MagicMock()

        class _ResourceNotFound(Exception):
            pass

        client.exceptions.ResourceNotFoundException = _ResourceNotFound

        if provider_exists:
            client.describe_identity_provider.return_value = {"IdentityProvider": {}}
        else:
            client.describe_identity_provider.side_effect = _ResourceNotFound()

        clients = []
        if bootstrap_client is not None:
            clients.append(bootstrap_client)
        client.list_user_pool_clients.return_value = {"UserPoolClients": clients}

        return client

    @patch("boto3.client")
    @patch("pathlib.Path.exists", return_value=True)
    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_creates_saml_provider_when_absent(self, mock_get_profile, mock_exists, mock_boto_client, capsys):
        mock_get_profile.return_value = _profile()

        deployment_info = {
            "userPoolId": "us-east-1_abc123",
            "clientId": "web-client-id",
            "landingPageUrl": "https://d123.cloudfront.net",
            "region": "us-east-1",
        }
        cognito_client = self._mock_cognito_client(
            provider_exists=False,
            bootstrap_client={"ClientId": "bootstrap-client-id", "ClientName": "claude-code-test-bootstrap"},
        )
        mock_boto_client.return_value = cognito_client

        with patch("pathlib.Path.read_text", return_value=json.dumps(deployment_info)):
            tester = _run(metadata_url="https://example.com/saml/metadata")

        assert tester.status_code == 0
        cognito_client.create_identity_provider.assert_called_once()
        create_kwargs = cognito_client.create_identity_provider.call_args.kwargs
        assert create_kwargs["UserPoolId"] == "us-east-1_abc123"
        assert create_kwargs["ProviderName"] == "IAMIdentityCenter"
        assert create_kwargs["ProviderType"] == "SAML"
        assert create_kwargs["ProviderDetails"]["MetadataURL"] == "https://example.com/saml/metadata"
        cognito_client.update_identity_provider.assert_not_called()

        # Web app client updated with both providers enabled
        web_update = cognito_client.update_user_pool_client.call_args_list[0].kwargs
        assert web_update["ClientId"] == "web-client-id"
        assert "IAMIdentityCenter" in web_update["SupportedIdentityProviders"]
        assert "COGNITO" in web_update["SupportedIdentityProviders"]

        # Bootstrap client also updated
        bootstrap_update = cognito_client.update_user_pool_client.call_args_list[1].kwargs
        assert bootstrap_update["ClientId"] == "bootstrap-client-id"
        assert "IAMIdentityCenter" in bootstrap_update["SupportedIdentityProviders"]

        output = capsys.readouterr().out
        assert "SAML provider created" in output
        assert "Bootstrap client updated" in output

    @patch("boto3.client")
    @patch("pathlib.Path.exists", return_value=True)
    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_updates_existing_saml_provider(self, mock_get_profile, mock_exists, mock_boto_client):
        """An existing IAMIdentityCenter provider must be updated, not recreated."""
        mock_get_profile.return_value = _profile()

        deployment_info = {
            "userPoolId": "us-east-1_abc123",
            "clientId": "web-client-id",
            "landingPageUrl": "https://d123.cloudfront.net",
            "region": "us-east-1",
        }
        cognito_client = self._mock_cognito_client(provider_exists=True, bootstrap_client=None)
        mock_boto_client.return_value = cognito_client

        with patch("pathlib.Path.read_text", return_value=json.dumps(deployment_info)):
            tester = _run(metadata_url="https://example.com/saml/metadata")

        assert tester.status_code == 0
        cognito_client.create_identity_provider.assert_not_called()
        cognito_client.update_identity_provider.assert_called_once()
        update_kwargs = cognito_client.update_identity_provider.call_args.kwargs
        assert update_kwargs["ProviderName"] == "IAMIdentityCenter"
        assert update_kwargs["ProviderDetails"]["MetadataURL"] == "https://example.com/saml/metadata"

    @patch("boto3.client")
    @patch("pathlib.Path.exists", return_value=True)
    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_no_bootstrap_client_is_non_fatal(self, mock_get_profile, mock_exists, mock_boto_client, capsys):
        """When no bootstrap client exists, the command must succeed (dynamic config just isn't enabled)."""
        mock_get_profile.return_value = _profile()

        deployment_info = {
            "userPoolId": "us-east-1_abc123",
            "clientId": "web-client-id",
            "landingPageUrl": "https://d123.cloudfront.net",
            "region": "us-east-1",
        }
        cognito_client = self._mock_cognito_client(provider_exists=False, bootstrap_client=None)
        mock_boto_client.return_value = cognito_client

        with patch("pathlib.Path.read_text", return_value=json.dumps(deployment_info)):
            tester = _run(metadata_url="https://example.com/saml/metadata")

        assert tester.status_code == 0
        assert "No bootstrap client found" in capsys.readouterr().out
        # Only the web app client should have been updated (one call, not two)
        assert cognito_client.update_user_pool_client.call_count == 1

    @patch("boto3.client")
    @patch("pathlib.Path.exists", return_value=True)
    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_bootstrap_client_update_failure_is_non_fatal(
        self, mock_get_profile, mock_exists, mock_boto_client, capsys
    ):
        """A failure updating the bootstrap client must warn, not abort the whole command."""
        mock_get_profile.return_value = _profile()

        deployment_info = {
            "userPoolId": "us-east-1_abc123",
            "clientId": "web-client-id",
            "landingPageUrl": "https://d123.cloudfront.net",
            "region": "us-east-1",
        }
        cognito_client = self._mock_cognito_client(
            provider_exists=False,
            bootstrap_client={"ClientId": "bootstrap-client-id", "ClientName": "claude-code-test-bootstrap"},
        )

        def _update_side_effect(**kwargs):
            if kwargs.get("ClientId") == "bootstrap-client-id":
                raise Exception("boom")
            return {}

        cognito_client.update_user_pool_client.side_effect = _update_side_effect
        mock_boto_client.return_value = cognito_client

        with patch("pathlib.Path.read_text", return_value=json.dumps(deployment_info)):
            tester = _run(metadata_url="https://example.com/saml/metadata")

        # Command still reports overall success — web client succeeded, bootstrap failure is a warning.
        assert tester.status_code == 0
        assert "Could not update bootstrap client" in capsys.readouterr().out

    @patch("boto3.client")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_falls_back_to_cloudformation_outputs(self, mock_get_profile, mock_exists, mock_boto_client):
        """Without deployment-info.json, resolve User Pool/client IDs from CloudFormation stack outputs."""
        mock_get_profile.return_value = _profile()

        cfn_client = MagicMock()
        cfn_client.describe_stacks.side_effect = [
            {
                "Stacks": [
                    {
                        "Outputs": [
                            {"OutputKey": "UserPoolId", "OutputValue": "us-east-1_fromCfn"},
                            {"OutputKey": "UserPoolClientId", "OutputValue": "web-client-from-cfn"},
                        ]
                    }
                ]
            },
            {"Stacks": [{"Outputs": [{"OutputKey": "LandingPageUrl", "OutputValue": "https://cfn.cloudfront.net"}]}]},
        ]

        cognito_client = self._mock_cognito_client(provider_exists=False, bootstrap_client=None)

        def _client_factory(service_name, region_name=None):
            return cfn_client if service_name == "cloudformation" else cognito_client

        mock_boto_client.side_effect = _client_factory

        tester = _run(metadata_url="https://example.com/saml/metadata")

        assert tester.status_code == 0
        create_kwargs = cognito_client.create_identity_provider.call_args.kwargs
        assert create_kwargs["UserPoolId"] == "us-east-1_fromCfn"
        web_update = cognito_client.update_user_pool_client.call_args_list[0].kwargs
        assert web_update["ClientId"] == "web-client-from-cfn"


class TestProfileOptionOverride:
    """The --profile option must be forwarded to Config.get_profile() by name."""

    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_explicit_profile_name_passed_through(self, mock_get_profile, capsys):
        named_profile = _profile(name="other-profile", distribution_type="presigned-s3")
        mock_get_profile.return_value = named_profile

        tester = _run(profile_option="other-profile")

        mock_get_profile.assert_called_once_with("other-profile")
        # named_profile has distribution_type="presigned-s3" -> command must reject it,
        # proving the named profile (not some other profile) was actually used.
        assert tester.status_code == 1
        assert "landing-page-idc" in capsys.readouterr().out

    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_no_profile_option_passes_none(self, mock_get_profile):
        """Without --profile, get_profile(None) is called, which resolves to the active profile."""
        mock_get_profile.return_value = _profile(distribution_type="presigned-s3")

        _run(profile_option=None)

        mock_get_profile.assert_called_once_with(None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
