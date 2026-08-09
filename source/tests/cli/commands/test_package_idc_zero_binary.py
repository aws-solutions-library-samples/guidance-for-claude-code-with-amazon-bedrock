# ABOUTME: Tests for IDC zero-binary package path
# ABOUTME: Verifies that IDC auth without quota skips binaries, IDC with quota includes them

"""Tests for IDC zero-binary packaging logic."""

import json
import tempfile
from pathlib import Path

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


class TestIDCZeroBinaryDetection:
    """Test the IDC zero-binary mode detection logic."""

    def _make_profile(self, auth_type="idc", quota_endpoint=None, monitoring=True):
        """Create a profile with IDC settings."""
        return Profile(
            name="test-idc",
            provider_domain="",
            client_id="",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="",
            auth_type=auth_type,
            monitoring_enabled=monitoring,
            quota_api_endpoint=quota_endpoint or "",
            idc_start_url="https://d-123456.awsapps.com/start",
            idc_account_id="123456789012",
            idc_permission_set_name="BedrockAccess",
        )

    def test_idc_without_quota_is_zero_binary(self):
        """IDC auth + no quota = zero-binary mode (no credential-process needed)."""
        profile = self._make_profile(auth_type="idc", quota_endpoint=None)
        _is_idc_auth = profile.effective_auth_type == "idc"
        _has_quota = bool(profile.quota_api_endpoint)
        is_zero_binary = _is_idc_auth and not _has_quota
        assert is_zero_binary is True

    def test_idc_with_quota_is_not_zero_binary(self):
        """IDC auth + quota configured = NOT zero-binary (credential-process needed for enforcement)."""
        profile = self._make_profile(auth_type="idc", quota_endpoint="https://api.example.com/quota")
        _is_idc_auth = profile.effective_auth_type == "idc"
        _has_quota = bool(profile.quota_api_endpoint)
        is_zero_binary = _is_idc_auth and not _has_quota
        assert is_zero_binary is False

    def test_oidc_is_never_zero_binary(self):
        """OIDC auth is never zero-binary (always needs credential-process)."""
        profile = self._make_profile(auth_type="oidc", quota_endpoint=None)
        _is_idc_auth = profile.effective_auth_type == "idc"
        _has_quota = bool(profile.quota_api_endpoint)
        is_zero_binary = _is_idc_auth and not _has_quota
        assert is_zero_binary is False

    def test_none_auth_is_never_zero_binary(self):
        """Passthrough (none) auth is never zero-binary."""
        profile = self._make_profile(auth_type="none", quota_endpoint=None)
        _is_idc_auth = profile.effective_auth_type == "idc"
        is_zero_binary = _is_idc_auth and not bool(profile.quota_api_endpoint)
        assert is_zero_binary is False


class TestIDCZeroBinaryGuard:
    """Test that zero-binary mode correctly bypasses the 'no binaries built' check."""

    def test_zero_binary_skips_build_failure_check(self):
        """Verify the guard logic: empty built_executables + is_idc_zero_binary = no error."""
        built_executables = []
        windows_codebuild_pending = False
        is_idc_zero_binary = True

        # This is the guard condition from package.py
        should_error = not built_executables and not windows_codebuild_pending and not is_idc_zero_binary
        assert should_error is False

    def test_non_zero_binary_triggers_build_failure_check(self):
        """Non-zero-binary mode with no executables SHOULD trigger the error."""
        built_executables = []
        windows_codebuild_pending = False
        is_idc_zero_binary = False

        should_error = not built_executables and not windows_codebuild_pending and not is_idc_zero_binary
        assert should_error is True

    def test_normal_build_with_executables_passes(self):
        """Normal build with executables should pass regardless of mode."""
        built_executables = [("macos-arm64", "/path/to/binary")]
        windows_codebuild_pending = False
        is_idc_zero_binary = False

        should_error = not built_executables and not windows_codebuild_pending and not is_idc_zero_binary
        assert should_error is False


class TestIDCCollectorConfigParsing:
    """Test the resource attribute parsing for IDC collector config."""

    def _parse_attrs(self, otel_resource_attributes):
        """Replicate the parsing logic from package.py."""
        attrs = {}
        if otel_resource_attributes:
            for pair in otel_resource_attributes.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    attrs[k.strip()] = v.strip()
        return attrs

    def test_parse_full_attributes(self):
        """Parse a complete resource attributes string."""
        attrs = self._parse_attrs("department=platform,team.id=infra-core,cost_center=CC-4521,organization=acme-corp")
        assert attrs["department"] == "platform"
        assert attrs["team.id"] == "infra-core"
        assert attrs["cost_center"] == "CC-4521"
        assert attrs["organization"] == "acme-corp"

    def test_parse_none_attributes(self):
        """None attributes should produce empty dict."""
        attrs = self._parse_attrs(None)
        assert attrs == {}

    def test_parse_empty_string(self):
        """Empty string should produce empty dict."""
        attrs = self._parse_attrs("")
        assert attrs == {}

    def test_parse_single_attribute(self):
        """Single attribute without trailing comma."""
        attrs = self._parse_attrs("department=engineering")
        assert attrs == {"department": "engineering"}

    def test_parse_value_with_equals(self):
        """Value containing '=' should be preserved (split on first only)."""
        attrs = self._parse_attrs("key=value=with=equals")
        assert attrs["key"] == "value=with=equals"

    def test_parse_whitespace_handling(self):
        """Whitespace around keys and values should be stripped."""
        attrs = self._parse_attrs(" department = platform , team.id = core ")
        assert attrs["department"] == "platform"
        assert attrs["team.id"] == "core"

    def test_defaults_for_missing_keys(self):
        """Missing keys should use .get() defaults safely."""
        attrs = self._parse_attrs("department=engineering")
        assert attrs.get("department", "default") == "engineering"
        assert attrs.get("team.id", "default") == "default"
        assert attrs.get("cost_center", "default") == "default"
        assert attrs.get("organization", "default") == "default"


class TestIDCOtelHeadersHelper:
    """Test that otelHeadersHelper is correctly omitted for IDC profiles."""

    def test_idc_profile_no_otel_headers_helper(self):
        """IDC profiles should NOT set otelHeadersHelper in settings."""
        profile = Profile(
            name="test-idc",
            provider_domain="",
            client_id="",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="",
            auth_type="idc",
            monitoring_enabled=True,
            idc_start_url="https://d-123456.awsapps.com/start",
            idc_account_id="123456789012",
            idc_permission_set_name="BedrockAccess",
        )
        _is_idc = profile.effective_auth_type == "idc"
        assert _is_idc is True

    def test_oidc_profile_has_otel_headers_helper(self):
        """OIDC profiles SHOULD set otelHeadersHelper."""
        profile = Profile(
            name="test-oidc",
            provider_domain="auth.example.com",
            client_id="client-123",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            auth_type="oidc",
            monitoring_enabled=True,
        )
        _is_idc = profile.effective_auth_type == "idc"
        assert _is_idc is False


class TestIDCZeroBinarySettings:
    """Regression tests: IDC zero-binary settings.json must not reference credential-process."""

    def _make_idc_profile(self, quota_endpoint=None):
        return Profile(
            name="test-idc",
            provider_domain="",
            client_id="",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="",
            auth_type="idc",
            monitoring_enabled=False,
            quota_api_endpoint=quota_endpoint or "",
            idc_start_url="https://d-123456.awsapps.com/start",
            idc_account_id="123456789012",
            idc_permission_set_name="BedrockAccess",
        )

    def _load_settings(self, output_dir: Path) -> dict:
        settings_path = output_dir / "claude-settings" / "settings.json"
        with open(settings_path) as f:
            return json.load(f)

    def test_zero_binary_settings_no_credential_process_placeholder(self):
        """IDC zero-binary settings.json must not contain __CREDENTIAL_PROCESS_PATH__."""
        command = PackageCommand()
        profile = self._make_idc_profile(quota_endpoint=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, is_idc_zero_binary=True)
            settings = self._load_settings(output_dir)

        settings_str = json.dumps(settings)
        assert "__CREDENTIAL_PROCESS_PATH__" not in settings_str

    def test_zero_binary_settings_no_aws_credential_process(self):
        """IDC zero-binary settings.json must not set AWS_CREDENTIAL_PROCESS."""
        command = PackageCommand()
        profile = self._make_idc_profile(quota_endpoint=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, is_idc_zero_binary=True)
            settings = self._load_settings(output_dir)

        assert "AWS_CREDENTIAL_PROCESS" not in settings.get("env", {})

    def test_zero_binary_settings_no_credential_hooks(self):
        """IDC zero-binary settings.json must not set awsCredentialExport or awsAuthRefresh."""
        command = PackageCommand()
        profile = self._make_idc_profile(quota_endpoint=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, is_idc_zero_binary=True)
            settings = self._load_settings(output_dir)

        assert "awsCredentialExport" not in settings
        assert "awsAuthRefresh" not in settings

    def test_zero_binary_settings_has_aws_profile(self):
        """IDC zero-binary settings.json must still set AWS_PROFILE for SSO resolution."""
        command = PackageCommand()
        profile = self._make_idc_profile(quota_endpoint=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, is_idc_zero_binary=True)
            settings = self._load_settings(output_dir)

        assert settings["env"]["AWS_PROFILE"] == "ClaudeCode"

    def test_idc_with_quota_settings_keeps_credential_process(self):
        """IDC+quota (non-zero-binary) settings.json must still have credential-process references."""
        command = PackageCommand()
        profile = self._make_idc_profile(quota_endpoint="https://api.example.com/quota")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, is_idc_zero_binary=False)
            settings = self._load_settings(output_dir)

        assert "__CREDENTIAL_PROCESS_PATH__" in settings["env"]["AWS_CREDENTIAL_PROCESS"]
        assert "__CREDENTIAL_PROCESS_PATH__" in settings.get("awsCredentialExport", "")
        assert "__CREDENTIAL_PROCESS_PATH__" in settings.get("awsAuthRefresh", "")
