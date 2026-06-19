"""Regression tests for Google OAuth client_secret support.

Google Desktop OAuth requires a client_secret for token exchange (unlike Okta/Auth0
which use PKCE-only for native apps). Google documents this secret as non-confidential
for installed applications, so it's stored in config.json rather than the OS keyring.
"""

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest


class TestGoogleClientSecretConfig:
    """Verify client_secret is read from config.json for Google provider."""

    def test_config_go_struct_has_client_secret_field(self):
        """The Go ProfileConfig struct must declare client_secret."""
        config_go = (
            Path(__file__).resolve().parents[2]
            / "source"
            / "go"
            / "internal"
            / "config"
            / "config.go"
        )
        if not config_go.exists():
            pytest.skip("Go source not found")
        content = config_go.read_text(encoding="utf-8")
        assert 'json:"client_secret' in content, (
            "ProfileConfig must have a ClientSecret field with "
            'json:"client_secret" tag for Google OAuth support'
        )

    def test_credential_process_reads_client_secret_for_non_azure(self):
        """resolveConfidentialAuth must check cfg.ClientSecret for non-Azure providers."""
        main_go = (
            Path(__file__).resolve().parents[2]
            / "source"
            / "go"
            / "cmd"
            / "credential-process"
            / "main.go"
        )
        if not main_go.exists():
            pytest.skip("Go source not found")
        content = main_go.read_text(encoding="utf-8")
        # The function should read ClientSecret when provider is not Azure
        assert "a.cfg.ClientSecret" in content, (
            "resolveConfidentialAuth must read ClientSecret from config "
            "for non-Azure providers (Google needs it for token exchange)"
        )

    def test_init_wizard_prompts_google_secret(self):
        """The init wizard must prompt for client_secret when provider is Google."""
        init_py = (
            Path(__file__).resolve().parents[2]
            / "source"
            / "claude_code_with_bedrock"
            / "cli"
            / "commands"
            / "init.py"
        )
        content = init_py.read_text(encoding="utf-8")
        # Verify Google-specific handling exists in init wizard
        assert 'provider_type = "google"' in content
        # client_secret is stored in OS keyring, not written to config file
        assert 'client_secret' in content, (
            "Init wizard must handle client_secret for Google provider (stored in keyring)"
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
            Path(__file__).resolve().parents[2]
            / "source"
            / "claude_code_with_bedrock"
            / "cli"
            / "commands"
            / "init.py"
        )
        content = init_py.read_text(encoding="utf-8")
        # Find the Google block and verify it writes to config, not keyring
        lines = content.splitlines()
        in_google_block = False
        for i, line in enumerate(lines):
            if 'provider_type == "google"' in line and "client_secret" not in line:
                in_google_block = True
                block_start = i
            elif in_google_block:
                if 'provider_type == "azure"' in line:
                    break  # reached end of google block
                assert "set_password" not in line, (
                    f"Line {i+1}: Google client_secret should be stored in config.json, "
                    f"not OS keyring (Google documents it as non-confidential)"
                )
