# ABOUTME: Tests for `ccwb configure-saml` — saves the SAML metadata URL to the profile
# ABOUTME: and re-deploys the CFN distribution stack so IdcSamlIdentityProvider gets created

"""Tests for ConfigureSamlCommand (CloudFormation-based implementation).

The IAM Identity Center landing page is distribution_type "landing-page" with
auth_type "idc" (beta vocabulary), deployed via landing-page-distribution.yaml
with AuthType=idc — the same template used by the other landing-page IdP types.
`ccwb configure-saml` doesn't call the Cognito API directly — it saves
distribution_saml_metadata_url to the profile and triggers a stack update via
DeployCommand._deploy_stack("distribution", ...), letting CloudFormation's
conditional IdcSamlIdentityProvider resource (and the callback-updater custom
resource) do the actual Cognito wiring.

Covers:
- Guard: command refuses to run for non-IDC profiles
- Guard: command fails cleanly when the distribution stack hasn't been deployed yet
- Happy path: saves metadata URL to profile, re-deploys, reports SAML status
- Stack update failure is surfaced, not swallowed
- --profile option forwarding
"""

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
        "distribution_type": "landing-page",
        "auth_type": "idc",
        "enable_distribution": True,
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
    """The command must refuse to run for anything other than the IDC landing page."""

    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_rejects_non_idc_distribution_type(self, mock_get_profile, capsys):
        # A landing page with OIDC (not IDC) auth must be rejected.
        mock_get_profile.return_value = _profile(distribution_type="landing-page", auth_type="oidc")
        tester = _run()
        assert tester.status_code == 1
        assert "auth_type='idc'" in capsys.readouterr().out

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


class TestStackExistenceGuard:
    """The distribution stack must already exist (for its ACS URL/Audience outputs)."""

    @patch("claude_code_with_bedrock.cli.commands.configure_saml.get_stack_outputs")
    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_missing_stack_fails_cleanly(self, mock_get_profile, mock_get_outputs, capsys):
        mock_get_profile.return_value = _profile()
        mock_get_outputs.return_value = None

        tester = _run()

        assert tester.status_code == 1
        output = capsys.readouterr().out
        assert "not found" in output
        assert "deploy distribution" in output


class TestSamlConfigurationFlow:
    """Happy-path: save metadata URL to profile, re-deploy, report SAML status."""

    @patch("claude_code_with_bedrock.cli.commands.deploy.CloudFormationManager")
    @patch("claude_code_with_bedrock.cli.commands.configure_saml.CloudFormationManager")
    @patch("claude_code_with_bedrock.cli.commands.deploy.get_stack_outputs")
    @patch("claude_code_with_bedrock.cli.commands.configure_saml.get_stack_outputs")
    @patch("claude_code_with_bedrock.config.Config.save_profile")
    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_saves_metadata_url_and_redeploys(
        self,
        mock_get_profile,
        mock_save_profile,
        mock_get_outputs_configure_saml,
        mock_get_outputs_deploy,
        MockConfigureSamlCFManager,
        MockDeployCFManager,
        capsys,
    ):
        profile = _profile()
        mock_get_profile.return_value = profile

        # configure_saml.py calls get_stack_outputs twice: once to verify the
        # stack exists (pre-SAML), once after redeploying (post-SAML status).
        mock_get_outputs_configure_saml.side_effect = [
            {"DistributionURL": "https://downloads.example.com", "IdcSamlAcsUrl": "https://x/saml2/idpresponse"},
            {
                "DistributionURL": "https://downloads.example.com",
                "IdcSamlConfigurationStatus": "✓ SAML identity provider configured",
            },
        ]
        # deploy.py's _deploy_stack("distribution", ...) separately looks up the
        # networking stack's VpcId/SubnetIds outputs before building CFN params.
        # The IDC landing page defaults ALBScheme to internal, which requires the
        # networking stack's NAT-routed PrivateSubnetIds output.
        mock_get_outputs_deploy.return_value = {
            "VpcId": "vpc-123",
            "SubnetIds": "subnet-1,subnet-2",
            "PrivateSubnetIds": "subnet-priv-1,subnet-priv-2",
        }

        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.outputs = {}
        mock_manager.deploy_stack.return_value = mock_result
        MockDeployCFManager.return_value = mock_manager
        MockConfigureSamlCFManager.return_value = mock_manager

        tester = _run(metadata_url="https://portal.sso.us-east-1.amazonaws.com/saml/metadata/abc")

        assert tester.status_code == 0

        # Metadata URL was saved to the profile before redeploying.
        assert profile.distribution_saml_metadata_url == "https://portal.sso.us-east-1.amazonaws.com/saml/metadata/abc"
        mock_save_profile.assert_called_once()

        # The stack update actually happened (deploy_stack invoked with the
        # distribution template and SamlMetadataUrl param). Parameters are
        # in boto3 ParameterKey/ParameterValue dict format at this point
        # (deploy.py's _convert_params_to_boto3 already ran).
        mock_manager.deploy_stack.assert_called_once()
        call_kwargs = mock_manager.deploy_stack.call_args.kwargs
        params = call_kwargs.get("parameters") or []
        assert {
            "ParameterKey": "SamlMetadataUrl",
            "ParameterValue": "https://portal.sso.us-east-1.amazonaws.com/saml/metadata/abc",
        } in params

        output = capsys.readouterr().out
        assert "SAML Configuration Complete" in output
        assert "SAML identity provider configured" in output

    @patch("claude_code_with_bedrock.cli.commands.deploy.CloudFormationManager")
    @patch("claude_code_with_bedrock.cli.commands.configure_saml.CloudFormationManager")
    @patch("claude_code_with_bedrock.cli.commands.deploy.get_stack_outputs")
    @patch("claude_code_with_bedrock.cli.commands.configure_saml.get_stack_outputs")
    @patch("claude_code_with_bedrock.config.Config.save_profile")
    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_stack_update_failure_is_surfaced(
        self,
        mock_get_profile,
        mock_save_profile,
        mock_get_outputs_configure_saml,
        mock_get_outputs_deploy,
        MockConfigureSamlCFManager,
        MockDeployCFManager,
        capsys,
    ):
        """A failed stack update must not be reported as success."""
        profile = _profile()
        mock_get_profile.return_value = profile
        mock_get_outputs_configure_saml.return_value = {"DistributionURL": "https://downloads.example.com"}
        mock_get_outputs_deploy.return_value = {"VpcId": "vpc-123", "SubnetIds": "subnet-1,subnet-2"}

        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Stack update failed: some resource error"
        mock_result.outputs = {}
        mock_manager.deploy_stack.return_value = mock_result
        MockDeployCFManager.return_value = mock_manager
        MockConfigureSamlCFManager.return_value = mock_manager

        tester = _run()

        assert tester.status_code != 0
        output = capsys.readouterr().out
        assert "SAML Configuration Complete" not in output


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
        assert "auth_type='idc'" in capsys.readouterr().out

    @patch("claude_code_with_bedrock.config.Config.get_profile")
    def test_no_profile_option_passes_none(self, mock_get_profile):
        """Without --profile, get_profile(None) is called, which resolves to the active profile."""
        mock_get_profile.return_value = _profile(distribution_type="presigned-s3")

        _run(profile_option=None)

        mock_get_profile.assert_called_once_with(None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
