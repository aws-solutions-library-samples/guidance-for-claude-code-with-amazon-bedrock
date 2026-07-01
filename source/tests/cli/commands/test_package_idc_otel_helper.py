# ABOUTME: Regression tests for otelHeadersHelper wiring across auth types
# ABOUTME: IDC-with-binary must wire the helper so dashboards attribute metrics per user

"""Regression tests: otelHeadersHelper is wired whenever a binary can resolve identity.

The CloudWatch dashboards aggregate usage by `user.email`. The central collector
sets that dimension from the `x-user-email` request header, which Claude Code only
sends when `otelHeadersHelper` points at the otel-helper binary.

For IDC, the credential-process binary resolves the user's email from the IAM ARN
session name and caches it (writeOtelCacheFromIDC / writeOtelCacheFromSTS); the
helper then serves it. So IDC deployments that ship the binary (e.g. quota enabled)
MUST wire otelHeadersHelper or every IDC user collapses to one static identity on
the dashboard.

Cases:
  - OIDC: helper wired (extracts attributes from JWT).
  - IDC + credential-process binary (quota_api_endpoint set): helper wired.
  - IDC zero-binary (no quota_api_endpoint): helper NOT wired — identity comes
    from the static collector config instead.
"""

import json
import tempfile
from pathlib import Path

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


def _base(**overrides) -> Profile:
    kwargs = {
        "name": "test",
        "provider_domain": "test.okta.com",
        "client_id": "test-client-id",
        "credential_storage": "session",
        "aws_region": "us-east-1",
        "identity_pool_name": "test-pool",
        "allowed_bedrock_regions": ["us-east-1", "us-west-2"],
        "cross_region_profile": "us",
        "monitoring_enabled": True,
        "otel_collector_endpoint": "https://collector.example.com",
        "stack_names": {"monitoring": "test-pool-otel-collector"},
    }
    kwargs.update(overrides)
    return Profile(**kwargs)


def _oidc_profile() -> Profile:
    return _base(auth_type="oidc", sso_enabled=True)


def _idc_with_binary_profile() -> Profile:
    # quota_api_endpoint set => credential-process binary is included.
    return _base(
        provider_domain="",
        client_id="",
        auth_type="idc",
        sso_enabled=False,
        idc_start_url="https://d-1234567890.awsapps.com/start",
        idc_account_id="123456789012",
        idc_permission_set_name="ClaudeCodeRole",
        quota_api_endpoint="https://quota.example.com/check",
    )


def _idc_zero_binary_profile() -> Profile:
    # No quota_api_endpoint => zero-binary IDC (static identity in collector).
    return _base(
        provider_domain="",
        client_id="",
        auth_type="idc",
        sso_enabled=False,
        idc_start_url="https://d-1234567890.awsapps.com/start",
        idc_account_id="123456789012",
        idc_permission_set_name="ClaudeCodeRole",
    )


def _read_settings(output_dir: Path) -> dict:
    with open(output_dir / "claude-settings" / "settings.json", encoding="utf-8") as f:
        return json.load(f)


def _generate(profile: Profile) -> dict:
    cmd = PackageCommand()
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir)
        cmd._create_claude_settings(out, profile, profile_name="test")
        return _read_settings(out)


class TestOtelHeadersHelperWiring:
    def test_oidc_wires_helper(self):
        settings = _generate(_oidc_profile())
        assert settings.get("otelHeadersHelper") == "__OTEL_HELPER_PATH__"

    def test_idc_with_binary_wires_helper(self):
        """The bug: IDC + binary previously skipped the helper, so dashboards
        attributed every IDC user to one static identity."""
        settings = _generate(_idc_with_binary_profile())
        assert settings.get("otelHeadersHelper") == "__OTEL_HELPER_PATH__", (
            "IDC with credential-process binary must wire otelHeadersHelper for per-user attribution"
        )

    def test_idc_zero_binary_does_not_wire_helper(self):
        """Zero-binary IDC has no runtime identity resolver; attribution comes
        from the static collector config, so the helper must stay unset."""
        settings = _generate(_idc_zero_binary_profile())
        assert "otelHeadersHelper" not in settings
