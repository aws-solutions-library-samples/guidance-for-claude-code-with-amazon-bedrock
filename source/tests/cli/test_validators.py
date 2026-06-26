# ABOUTME: Unit tests for configuration validators (validators.py)
# ABOUTME: Ensures packaging-time validation catches misconfigurations early

"""Tests for the configuration validators."""

from types import SimpleNamespace

from claude_code_with_bedrock.cli.validators import ValidationError, validate_profile_for_packaging


def _make_profile(**kwargs):
    """Create a minimal profile-like object with sensible defaults."""
    defaults = {
        "effective_auth_type": "oidc",
        "auth_type": "oidc",
        "provider_domain": "test.okta.com",
        "oidc_issuer_url": None,
        "client_id": "test-client-id",
        "aws_region": "us-east-1",
        "allowed_bedrock_regions": None,
        "monitoring_enabled": False,
        "otel_collector_endpoint": None,
        "cowork_config_mode": "static",
        "quota_enforcement_mode": "off",
        "quota_api_endpoint": None,
        "idc_start_url": None,
        "idc_account_id": None,
        "idc_permission_set_name": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestValidateOIDCProfile:
    """Tests for OIDC profile validation."""

    def test_valid_oidc_profile_no_errors(self):
        """A valid OIDC profile should produce no errors."""
        profile = _make_profile()
        errors = validate_profile_for_packaging(profile)
        assert errors == []

    def test_oidc_missing_client_id(self):
        """OIDC without client_id should produce an error."""
        profile = _make_profile(client_id=None)
        errors = validate_profile_for_packaging(profile)
        error_fields = [e.field for e in errors if e.severity == "error"]
        assert "client_id" in error_fields

    def test_oidc_missing_provider_domain_and_issuer_url(self):
        """OIDC without provider_domain or oidc_issuer_url should produce an error."""
        profile = _make_profile(provider_domain=None, oidc_issuer_url=None)
        errors = validate_profile_for_packaging(profile)
        error_fields = [e.field for e in errors if e.severity == "error"]
        assert "provider_domain" in error_fields

    def test_oidc_with_issuer_url_instead_of_domain(self):
        """OIDC with oidc_issuer_url (no provider_domain) should be valid."""
        profile = _make_profile(provider_domain=None, oidc_issuer_url="https://issuer.example.com")
        errors = validate_profile_for_packaging(profile)
        assert errors == []


class TestValidateIDCProfile:
    """Tests for IDC profile validation."""

    def test_valid_idc_profile_no_errors(self):
        """A valid IDC profile should produce no errors."""
        profile = _make_profile(
            effective_auth_type="idc",
            auth_type="idc",
            idc_start_url="https://d-12345.awsapps.com/start",
            idc_account_id="123456789012",
            idc_permission_set_name="AdministratorAccess",
        )
        errors = validate_profile_for_packaging(profile)
        assert errors == []

    def test_idc_missing_start_url(self):
        """IDC without idc_start_url should produce an error."""
        profile = _make_profile(
            effective_auth_type="idc",
            auth_type="idc",
            idc_start_url=None,
            idc_account_id="123456789012",
            idc_permission_set_name="AdministratorAccess",
        )
        errors = validate_profile_for_packaging(profile)
        error_fields = [e.field for e in errors if e.severity == "error"]
        assert "idc_start_url" in error_fields

    def test_idc_missing_account_id(self):
        """IDC without idc_account_id should produce an error."""
        profile = _make_profile(
            effective_auth_type="idc",
            auth_type="idc",
            idc_start_url="https://d-12345.awsapps.com/start",
            idc_account_id=None,
            idc_permission_set_name="AdministratorAccess",
        )
        errors = validate_profile_for_packaging(profile)
        error_fields = [e.field for e in errors if e.severity == "error"]
        assert "idc_account_id" in error_fields

    def test_idc_missing_permission_set(self):
        """IDC without idc_permission_set_name should produce an error."""
        profile = _make_profile(
            effective_auth_type="idc",
            auth_type="idc",
            idc_start_url="https://d-12345.awsapps.com/start",
            idc_account_id="123456789012",
            idc_permission_set_name=None,
        )
        errors = validate_profile_for_packaging(profile)
        error_fields = [e.field for e in errors if e.severity == "error"]
        assert "idc_permission_set_name" in error_fields


class TestValidateRegion:
    """Tests for region validation."""

    def test_missing_region(self):
        """Missing aws_region should produce an error."""
        profile = _make_profile(aws_region=None)
        errors = validate_profile_for_packaging(profile)
        error_fields = [e.field for e in errors if e.severity == "error"]
        assert "aws_region" in error_fields

    def test_region_not_in_allowed_list_is_warning(self):
        """Region not in allowed_bedrock_regions should produce a warning (not error)."""
        profile = _make_profile(
            aws_region="eu-west-1",
            allowed_bedrock_regions=["us-east-1", "us-west-2"],
        )
        errors = validate_profile_for_packaging(profile)
        warnings = [e for e in errors if e.severity == "warning"]
        error_only = [e for e in errors if e.severity == "error"]
        assert len(warnings) == 1
        assert warnings[0].field == "aws_region"
        assert error_only == []


class TestValidateMonitoring:
    """Tests for monitoring configuration validation."""

    def test_monitoring_enabled_no_endpoint_static_is_warning(self):
        """Monitoring enabled + no endpoint + static config mode should produce a warning."""
        profile = _make_profile(
            monitoring_enabled=True,
            otel_collector_endpoint=None,
            cowork_config_mode="static",
        )
        errors = validate_profile_for_packaging(profile)
        warnings = [e for e in errors if e.severity == "warning"]
        assert any(e.field == "otel_collector_endpoint" for e in warnings)

    def test_monitoring_enabled_no_endpoint_dynamic_no_warning(self):
        """Monitoring enabled + no endpoint + dynamic config mode should NOT produce a warning."""
        profile = _make_profile(
            monitoring_enabled=True,
            otel_collector_endpoint=None,
            cowork_config_mode="dynamic",
        )
        errors = validate_profile_for_packaging(profile)
        otel_issues = [e for e in errors if e.field == "otel_collector_endpoint"]
        assert otel_issues == []

    def test_monitoring_enabled_with_endpoint_no_warning(self):
        """Monitoring enabled with endpoint should produce no monitoring warning."""
        profile = _make_profile(
            monitoring_enabled=True,
            otel_collector_endpoint="http://localhost:4318",
            cowork_config_mode="static",
        )
        errors = validate_profile_for_packaging(profile)
        otel_issues = [e for e in errors if e.field == "otel_collector_endpoint"]
        assert otel_issues == []


class TestValidateBootstrapIDCConflict:
    """Tests for bootstrap server + IDC conflict."""

    def test_dynamic_config_with_idc_is_error(self):
        """Dynamic config mode + IDC auth should produce an error."""
        profile = _make_profile(
            effective_auth_type="idc",
            auth_type="idc",
            cowork_config_mode="dynamic",
            idc_start_url="https://d-12345.awsapps.com/start",
            idc_account_id="123456789012",
            idc_permission_set_name="AdministratorAccess",
        )
        errors = validate_profile_for_packaging(profile)
        error_fields = [e.field for e in errors if e.severity == "error"]
        assert "cowork_config_mode" in error_fields

    def test_dynamic_config_with_oidc_no_error(self):
        """Dynamic config mode + OIDC auth should NOT produce this error."""
        profile = _make_profile(
            cowork_config_mode="dynamic",
        )
        errors = validate_profile_for_packaging(profile)
        config_issues = [e for e in errors if e.field == "cowork_config_mode"]
        assert config_issues == []


class TestValidateQuotaEnforcement:
    """Tests for quota enforcement validation."""

    def test_quota_enforcement_without_endpoint_is_error(self):
        """Quota enforcement enabled without quota_api_endpoint should produce an error."""
        profile = _make_profile(
            quota_enforcement_mode="strict",
            quota_api_endpoint=None,
        )
        errors = validate_profile_for_packaging(profile)
        error_fields = [e.field for e in errors if e.severity == "error"]
        assert "quota_api_endpoint" in error_fields

    def test_quota_enforcement_with_endpoint_no_error(self):
        """Quota enforcement enabled with endpoint should produce no error."""
        profile = _make_profile(
            quota_enforcement_mode="strict",
            quota_api_endpoint="https://quota.example.com/api",
        )
        errors = validate_profile_for_packaging(profile)
        quota_issues = [e for e in errors if e.field == "quota_api_endpoint"]
        assert quota_issues == []

    def test_quota_enforcement_off_no_error(self):
        """Quota enforcement off should produce no quota-related error."""
        profile = _make_profile(
            quota_enforcement_mode="off",
            quota_api_endpoint=None,
        )
        errors = validate_profile_for_packaging(profile)
        quota_issues = [e for e in errors if e.field == "quota_api_endpoint"]
        assert quota_issues == []
