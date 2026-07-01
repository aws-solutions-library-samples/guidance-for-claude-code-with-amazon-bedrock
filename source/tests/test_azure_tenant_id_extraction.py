"""Regression test for issue #351: Azure tenant ID extraction.

The distribution deploy path must extract the tenant GUID from Azure
provider domain URLs, not pass the full URL as AzureTenantId. The auth
deploy path was fixed in #53, but the distribution path was missed.
"""

import pytest

from claude_code_with_bedrock.cli.commands.deploy import _extract_azure_tenant_id


class TestAzureTenantIdExtraction:
    """Pin Azure tenant ID extraction to prevent URL duplication regression."""

    VALID_GUID = "abc12345-1234-5678-9abc-def012345678"

    @pytest.mark.parametrize(
        "input_domain",
        [
            "login.microsoftonline.com/abc12345-1234-5678-9abc-def012345678/v2.0",
            "https://login.microsoftonline.com/abc12345-1234-5678-9abc-def012345678/v2.0",
            "login.microsoftonline.com/abc12345-1234-5678-9abc-def012345678",
            "https://login.microsoftonline.com/abc12345-1234-5678-9abc-def012345678",
            "abc12345-1234-5678-9abc-def012345678",
        ],
        ids=["domain/guid/v2.0", "https://domain/guid/v2.0", "domain/guid", "https://domain/guid", "bare-guid"],
    )
    def test_extracts_guid_from_various_formats(self, input_domain):
        """Tenant GUID is correctly extracted from all supported URL formats."""
        result = _extract_azure_tenant_id(input_domain)
        assert result == self.VALID_GUID, (
            f"Expected bare GUID '{self.VALID_GUID}' but got '{result}' from input '{input_domain}'"
        )

    def test_result_is_bare_guid_not_url(self):
        """Result must never contain URL components like 'login' or 'microsoftonline'."""
        domain = "login.microsoftonline.com/abc12345-1234-5678-9abc-def012345678/v2.0"
        result = _extract_azure_tenant_id(domain)
        assert "login" not in result
        assert "microsoftonline" not in result
        assert "/" not in result
        assert "https" not in result

    def test_passthrough_when_no_guid_found(self):
        """If no GUID pattern found, return input as-is (graceful fallback)."""
        result = _extract_azure_tenant_id("some-custom-domain.com")
        assert result == "some-custom-domain.com"

    def test_empty_string_passthrough(self):
        """Empty input returns empty string without crashing."""
        result = _extract_azure_tenant_id("")
        assert result == ""

    def test_distribution_path_uses_helper(self):
        """deploy.py must use _extract_azure_tenant_id for distribution Azure params.

        This prevents regression where distribution_idp_domain is passed raw
        as AzureTenantId (issue #351).
        """
        from pathlib import Path

        deploy_py = Path(__file__).resolve().parents[1] / "claude_code_with_bedrock" / "cli" / "commands" / "deploy.py"
        content = deploy_py.read_text(encoding="utf-8")

        # Ensure no raw domain is ever passed directly as AzureTenantId
        # Bad patterns: f"AzureTenantId={profile.provider_domain}"
        #               f"AzureTenantId={profile.distribution_idp_domain}"
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "AzureTenantId=" in line and "profile." in line and "_domain" in line:
                assert "_extract_azure_tenant_id" in line, (
                    f"Line {i + 1}: AzureTenantId parameter passes raw domain directly.\n"
                    f"  Found: {line.strip()}\n"
                    f"  Must use _extract_azure_tenant_id() to extract GUID.\n"
                    f"  This prevents issue #351 (URL duplication in distribution path)."
                )
