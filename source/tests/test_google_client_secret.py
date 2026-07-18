"""Regression tests for Google OAuth client_secret support.

Google Desktop OAuth requires a client_secret for token exchange (unlike Okta/Auth0
which use PKCE-only for native apps). Google documents this secret as non-confidential
for installed applications, so it's stored in config.json rather than the OS keyring.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ruff: noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claude_code_with_bedrock.cli.commands.init import InitCommand
from claude_code_with_bedrock.config import Config, Profile


class TestGoogleClientSecretConfig:
    """Verify client_secret is read from config.json for Google provider."""

    def test_config_go_struct_has_client_secret_field(self):
        """The Go ProfileConfig struct must declare client_secret."""
        config_go = Path(__file__).resolve().parents[2] / "source" / "go" / "internal" / "config" / "config.go"
        if not config_go.exists():
            pytest.skip("Go source not found")
        content = config_go.read_text(encoding="utf-8")
        assert 'json:"client_secret' in content, (
            'ProfileConfig must have a ClientSecret field with json:"client_secret" tag for Google OAuth support'
        )

    def test_credential_process_reads_client_secret_for_non_azure(self):
        """resolveConfidentialAuth must check cfg.ClientSecret for non-Azure providers."""
        main_go = Path(__file__).resolve().parents[2] / "source" / "go" / "cmd" / "credential-process" / "main.go"
        if not main_go.exists():
            pytest.skip("Go source not found")
        content = main_go.read_text(encoding="utf-8")
        # The function should read ClientSecret when provider is not Azure
        assert "a.cfg.ClientSecret" in content, (
            "resolveConfidentialAuth must read ClientSecret from config "
            "for non-Azure providers (Google needs it for token exchange)"
        )

    def test_init_wizard_prompts_google_secret(self):
        """The init wizard must have a Google branch that writes client_secret to config."""
        init_py = (
            Path(__file__).resolve().parents[2] / "source" / "claude_code_with_bedrock" / "cli" / "commands" / "init.py"
        )
        content = init_py.read_text(encoding="utf-8")
        # A Google-specific provider branch must exist (distinct from the Azure branch)
        # and must persist the secret to the config dict (not the keyring).
        assert 'elif provider_type == "google":' in content, (
            "Init wizard must have a Google branch that collects the OAuth client secret"
        )
        assert 'config["client_secret"] = client_secret' in content, (
            "Google branch must persist client_secret to config.json (non-confidential)"
        )

    def test_package_includes_google_client_secret(self):
        """package.py must include client_secret in config.json for Google."""
        package_py = (
            Path(__file__).resolve().parents[2]
            / "source"
            / "claude_code_with_bedrock"
            / "cli"
            / "commands"
            / "package.py"
        )
        content = package_py.read_text(encoding="utf-8")
        assert "client_secret" in content
        assert "google" in content.lower()

    def test_google_secret_not_in_keyring_path(self):
        """Google's client_secret must NOT use keyring (it's non-confidential)."""
        init_py = (
            Path(__file__).resolve().parents[2] / "source" / "claude_code_with_bedrock" / "cli" / "commands" / "init.py"
        )
        content = init_py.read_text(encoding="utf-8")
        # Find the Google block and verify it writes to config, not keyring
        lines = content.splitlines()
        in_google_block = False
        for i, line in enumerate(lines):
            if 'provider_type == "google"' in line and "client_secret" not in line:
                in_google_block = True
            elif in_google_block:
                if 'provider_type == "azure"' in line:
                    break  # reached end of google block
                assert "set_password" not in line, (
                    f"Line {i + 1}: Google client_secret should be stored in config.json, "
                    f"not OS keyring (Google documents it as non-confidential)"
                )


class TestGoogleClientSecretRoundTrip:
    """Re-running init must preserve a saved Google client_secret (config-sync.md)."""

    @staticmethod
    def _google_profile() -> Profile:
        return Profile(
            name="google-test",
            provider_domain="accounts.google.com",
            client_id="319-abc.apps.googleusercontent.com",
            identity_pool_name="claude-code-auth",
            credential_storage="session",
            aws_region="us-east-1",
            provider_type="google",
            client_secret="GOCSPX-secret-value",
            federation_type="direct",
            federated_role_arn="arn:aws:iam::123456789012:role/BedrockGoogleFederatedRole",
        )

    def test_rerun_preserves_google_client_secret(self):
        """_check_existing_deployment must restore client_secret from the saved profile."""
        command = InitCommand()
        fake_config = Config()
        profile = self._google_profile()
        with (
            patch.object(Config, "load", return_value=fake_config),
            patch.object(fake_config, "get_profile", return_value=profile),
            patch.object(InitCommand, "_stack_exists", side_effect=Exception("no creds")),
        ):
            rebuilt = command._check_existing_deployment("google-test")
        assert rebuilt.get("client_secret") == "GOCSPX-secret-value", (
            "Re-running init dropped the Google client_secret — it must survive the "
            "profile -> config rebuild so the value pre-fills instead of resetting"
        )

    def test_save_configuration_persists_client_secret(self):
        """_save_configuration must write client_secret into the saved Profile."""
        command = InitCommand()
        fake_config = Config()
        saved = {}

        def _capture(profile):
            saved["profile"] = profile

        config_data = {
            "provider_type": "google",
            "client_secret": "GOCSPX-secret-value",
            "sso_enabled": True,
            "credential_storage": "session",
            "okta": {"domain": "accounts.google.com", "client_id": "319-abc.apps.googleusercontent.com"},
            "aws": {
                "region": "us-east-1",
                "identity_pool_name": "claude-code-auth",
                "stacks": {},
                "allowed_bedrock_regions": ["us-east-1"],
            },
            "monitoring": {"enabled": False},
            "federation_type": "direct",
        }
        with (
            patch.object(Config, "load", return_value=fake_config),
            patch.object(fake_config, "get_profile", return_value=None),
            patch.object(fake_config, "add_profile", side_effect=_capture),
            patch.object(fake_config, "set_active_profile"),
            patch.object(fake_config, "save"),
        ):
            command._save_configuration(config_data, "google-test")

        assert saved["profile"].client_secret == "GOCSPX-secret-value", (
            "_save_configuration must persist the Google client_secret to the profile"
        )
