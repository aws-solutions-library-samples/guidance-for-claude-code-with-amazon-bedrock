# ABOUTME: Unit tests for package command with cross-region support
# ABOUTME: Tests that package command properly includes cross-region configuration

"""Tests for the package command."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


class TestPackageCommandCrossRegion:
    """Tests for package command cross-region functionality."""

    def test_config_includes_cross_region_profile(self):
        """Test that generated config.json includes cross_region_profile."""
        command = PackageCommand()

        # Create a test profile with cross-region settings
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client-id",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
            cross_region_profile="us",
            monitoring_enabled=False,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Call _create_config
            config_path = command._create_config(output_dir, profile, "test-identity-pool-id")

            # Read and verify the config
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

            assert "ClaudeCode" in config
            claude_config = config["ClaudeCode"]

            # Check all expected fields
            assert claude_config["provider_domain"] == "test.okta.com"
            assert claude_config["client_id"] == "test-client-id"
            assert claude_config["identity_pool_id"] == "test-identity-pool-id"
            assert claude_config["aws_region"] == "us-east-1"
            assert claude_config["cross_region_profile"] == "us"
            assert claude_config["credential_storage"] == "keyring"

    def test_config_defaults_cross_region_to_us(self):
        """Test that config defaults cross_region_profile to 'us' if not set."""
        command = PackageCommand()

        # Create profile without cross_region_profile
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-west-2",
            identity_pool_name="test-pool",
            allowed_bedrock_regions=["us-east-1", "us-west-2"],
            monitoring_enabled=False,
        )
        # Explicitly set to None to test default
        profile.cross_region_profile = None

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Call _create_config
            config_path = command._create_config(output_dir, profile, "test-pool-id")

            # Read and verify
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

            # Should default to 'us'
            assert config["ClaudeCode"]["cross_region_profile"] == "us"

    def test_installer_script_preserves_region(self):
        """Test that installer script correctly extracts region from config."""
        command = PackageCommand()

        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-west-2",  # Note: different from cross-region
            identity_pool_name="test-pool",
            allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
            cross_region_profile="us",
            monitoring_enabled=False,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Create installer
            installer_path = command._create_installer(
                output_dir, profile, [("macos", Path("credential-process-macos"))], []
            )

            # Read installer and check region extraction
            with open(installer_path, encoding="utf-8") as f:
                installer_content = f.read()

            # Should extract region from Claude settings first, then fallback to profile region
            assert "AWS_REGION" in installer_content or "aws_region" in installer_content
            # The fallback should now have the interpolated region value
            assert "us-west-2" in installer_content or "config.json" in installer_content


class TestResolveFederation:
    """Regression tests for federation identifier resolution.

    Guards against the bug where `ccwb package` used `identity_pool_name` (a
    human-readable name) as the Cognito identity pool ID, producing a config.json
    that failed Cognito GetId validation ([\\w-]+:[0-9a-f-]+).
    """

    def _profile(self, **overrides):
        defaults = {
            "name": "test",
            "provider_domain": "example.auth.us-east-1.amazoncognito.com",
            "client_id": "test-client-id",
            "credential_storage": "keyring",
            "aws_region": "us-east-1",
            "identity_pool_name": "claude-code-auth",  # a NAME, not the pool ID
            "federation_type": "cognito",
            "monitoring_enabled": False,
        }
        defaults.update(overrides)
        return Profile(**defaults)

    def test_cognito_resolves_pool_id_from_stack_not_name(self):
        """Cognito must use the stack's IdentityPoolId (region:uuid), never the
        identity_pool_name. Core regression guard for the GetId ValidationException."""
        command = PackageCommand()
        profile = self._profile()
        console = MagicMock()
        fake_outputs = {
            "FederationType": "cognito",
            "IdentityPoolId": "us-east-1:00000000-0000-0000-0000-000000000000",
        }
        with patch(
            "claude_code_with_bedrock.cli.commands.package.get_stack_outputs",
            return_value=fake_outputs,
        ):
            federation_type, identity_pool_id, federated_role_arn = command._resolve_federation(profile, console)

        assert federation_type == "cognito"
        assert identity_pool_id == "us-east-1:00000000-0000-0000-0000-000000000000"
        # Must NOT fall back to the human-readable name (the original bug)
        assert identity_pool_id != "claude-code-auth"
        assert federated_role_arn is None

    def test_direct_uses_profile_role_arn_without_stack(self):
        """Direct STS keeps the profile shortcut — the profile stores the real ARN."""
        command = PackageCommand()
        arn = "arn:aws:iam::123456789012:role/BedrockRole"
        profile = self._profile(federation_type="direct", federated_role_arn=arn)
        console = MagicMock()
        with patch("claude_code_with_bedrock.cli.commands.package.get_stack_outputs") as mock_stack:
            federation_type, identity_pool_id, federated_role_arn = command._resolve_federation(profile, console)

        assert federation_type == "direct"
        assert federated_role_arn == arn
        assert identity_pool_id is None
        mock_stack.assert_not_called()  # no stack lookup needed for direct shortcut

    def test_cognito_missing_pool_id_returns_none(self):
        """If the stack has no IdentityPoolId, resolution fails gracefully (no name fallback)."""
        command = PackageCommand()
        profile = self._profile()
        console = MagicMock()
        with patch(
            "claude_code_with_bedrock.cli.commands.package.get_stack_outputs",
            return_value={"FederationType": "cognito"},
        ):
            federation_type, identity_pool_id, federated_role_arn = command._resolve_federation(profile, console)

        assert identity_pool_id is None
        assert federated_role_arn is None

    def test_sso_disabled_returns_no_identifier(self):
        """SSO disabled needs no federation identifier and performs no stack lookup."""
        command = PackageCommand()
        profile = self._profile(sso_enabled=False)
        console = MagicMock()
        with patch("claude_code_with_bedrock.cli.commands.package.get_stack_outputs") as mock_stack:
            federation_type, identity_pool_id, federated_role_arn = command._resolve_federation(profile, console)

        assert identity_pool_id is None
        assert federated_role_arn is None
        mock_stack.assert_not_called()


class TestPackageCommandOtelDefaults:
    """Tests for the default OTEL_RESOURCE_ATTRIBUTES written into settings.json."""

    def _make_monitoring_profile(self):
        return Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            allowed_bedrock_regions=["us-east-1"],
            monitoring_enabled=True,
            stack_names={"monitoring": "test-otel-collector"},
        )

    def _render_settings(self, otel_resource_attributes=None):
        """Drive _create_claude_settings with a mocked monitoring stack endpoint."""
        command = PackageCommand()
        profile = self._make_monitoring_profile()

        fake_outputs = json.dumps(
            [{"OutputKey": "CollectorEndpoint", "OutputValue": "https://otel.example.com"}]
        )
        completed = MagicMock(returncode=0, stdout=fake_outputs)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with patch(
                "claude_code_with_bedrock.cli.commands.package.subprocess.run",
                return_value=completed,
            ):
                command._create_claude_settings(
                    output_dir,
                    profile,
                    include_coauthored_by=True,
                    profile_name="test",
                    otel_resource_attributes=otel_resource_attributes,
                )

            settings_path = output_dir / "claude-settings" / "settings.json"
            with open(settings_path, encoding="utf-8") as f:
                return json.load(f)

    def test_default_department_is_default_not_engineering(self):
        """Regression: the default department must be 'default', not 'engineering'.

        'engineering' is not a safe assumption for every deployment, so the
        baseline OTEL attributes should be neutral and overridable.
        """
        settings = self._render_settings()
        attrs = settings["env"]["OTEL_RESOURCE_ATTRIBUTES"]

        assert "department=default" in attrs
        assert "department=engineering" not in attrs

    def test_configured_attributes_override_default(self):
        """An explicit OTEL_RESOURCE_ATTRIBUTES value takes precedence over the default."""
        settings = self._render_settings(otel_resource_attributes="department=research,team.id=ml")
        attrs = settings["env"]["OTEL_RESOURCE_ATTRIBUTES"]

        assert attrs == "department=research,team.id=ml"
