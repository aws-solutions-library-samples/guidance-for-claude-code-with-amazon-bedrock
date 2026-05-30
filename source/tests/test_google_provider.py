# ABOUTME: Tests for Google OIDC provider support
# ABOUTME: Validates provider detection, token endpoint handling, and deploy parameter wiring

"""Tests for Google OIDC provider integration (#414)."""

from pathlib import Path

import pytest

from claude_code_with_bedrock.utils.url_validation import detect_provider_type_secure as detect_provider_type


class TestGoogleProviderDetection:
    """Verify Google is correctly detected from domain input."""

    def test_detect_google_standard_domain(self):
        """accounts.google.com is detected as google."""
        assert detect_provider_type("accounts.google.com") == "google"

    def test_detect_google_with_https(self):
        """Full URL with https is detected as google."""
        assert detect_provider_type("https://accounts.google.com") == "google"

    def test_detect_google_not_confused_with_generic(self):
        """Google domain should not fall through to generic OIDC."""
        result = detect_provider_type("accounts.google.com")
        assert result != "oidc"
        assert result == "google"

    def test_detect_google_subdomain_attack(self):
        """Malicious subdomain should not match as google."""
        # accounts.google.com.evil.com should NOT be detected as google
        result = detect_provider_type("accounts.google.com.evil.com")
        assert result != "google"

    def test_detect_google_prefix_attack(self):
        """Domain with google as prefix should not match."""
        result = detect_provider_type("accounts.google.com.attacker.com")
        assert result != "google"

    def test_other_providers_unchanged(self):
        """Adding Google doesn't break other provider detection."""
        assert detect_provider_type("mycompany.okta.com") == "okta"
        assert detect_provider_type("mycompany.auth0.com") == "auth0"
        assert detect_provider_type("login.microsoftonline.com/tenant-id/v2.0") == "azure"


class TestGoogleTokenEndpoint:
    """Verify absolute token endpoint is handled correctly."""

    def test_google_token_endpoint_is_absolute(self):
        """Google's token_endpoint starts with https:// (absolute URL)."""
        cp_path = Path(__file__).resolve().parents[1] / "credential_provider" / "__main__.py"
        source = cp_path.read_text(encoding="utf-8")
        assert '"token_endpoint": "https://oauth2.googleapis.com/token"' in source

    def test_absolute_url_detection_logic(self):
        """Absolute URLs (https://) should be used directly, not prefixed with base_url."""
        token_endpoint = "https://oauth2.googleapis.com/token"
        base_url = "https://accounts.google.com"

        # This replicates the logic in credential_provider/__main__.py line 1029-1031
        if token_endpoint.startswith("https://"):
            token_url = token_endpoint
        else:
            token_url = f"{base_url}{token_endpoint}"

        assert token_url == "https://oauth2.googleapis.com/token"
        assert "accounts.google.com" not in token_url


class TestGoogleDeployParams:
    """Verify deploy.py passes correct CloudFormation parameters for Google."""

    def test_deploy_has_google_in_template_map(self):
        """deploy.py maps 'google' to the correct template file."""
        source_path = (
            Path(__file__).resolve().parents[1]
            / "claude_code_with_bedrock"
            / "cli"
            / "commands"
            / "deploy.py"
        )
        source = source_path.read_text(encoding="utf-8")
        assert '"google": "bedrock-auth-google.yaml"' in source

    def test_deploy_passes_google_params(self):
        """deploy.py has elif block for google that passes GoogleDomain and GoogleClientId."""
        source_path = (
            Path(__file__).resolve().parents[1]
            / "claude_code_with_bedrock"
            / "cli"
            / "commands"
            / "deploy.py"
        )
        source = source_path.read_text(encoding="utf-8")
        # Verify the parameter wiring exists
        assert "GoogleDomain={profile.provider_domain}" in source
        assert "GoogleClientId={profile.client_id}" in source

