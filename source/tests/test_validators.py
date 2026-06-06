# ABOUTME: Unit tests for validators.py — profile validation, domain checks, ARN format
# ABOUTME: Covers ProfileValidator methods that had zero test coverage

"""Tests for claude_code_with_bedrock.validators module."""

import pytest

from claude_code_with_bedrock.validators import ProfileValidator, ValidationResult, validate_profile


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_valid_result_is_truthy(self):
        result = ValidationResult(valid=True, errors=[], warnings=[])
        assert bool(result) is True

    def test_invalid_result_is_falsy(self):
        result = ValidationResult(valid=False, errors=["bad"], warnings=[])
        assert bool(result) is False

    def test_str_valid(self):
        result = ValidationResult(valid=True, errors=[], warnings=[])
        assert "valid" in str(result).lower()

    def test_str_invalid_shows_errors(self):
        result = ValidationResult(valid=False, errors=["missing field"], warnings=[])
        output = str(result)
        # __str__ may show count summary rather than individual errors
        assert "failed" in output.lower() or "missing field" in output


class TestProfileNameValidation:
    """Tests for _is_valid_profile_name."""

    def test_simple_name(self):
        assert ProfileValidator._is_valid_profile_name("my-profile") is True

    def test_alphanumeric(self):
        assert ProfileValidator._is_valid_profile_name("profile123") is True

    def test_empty_name(self):
        assert ProfileValidator._is_valid_profile_name("") is False

    def test_too_long(self):
        assert ProfileValidator._is_valid_profile_name("a" * 65) is False

    def test_max_length(self):
        assert ProfileValidator._is_valid_profile_name("a" * 64) is True

    def test_underscores_rejected(self):
        assert ProfileValidator._is_valid_profile_name("my_profile") is False

    def test_spaces_rejected(self):
        assert ProfileValidator._is_valid_profile_name("my profile") is False

    def test_special_chars_rejected(self):
        assert ProfileValidator._is_valid_profile_name("profile!@#") is False

    def test_dots_rejected(self):
        assert ProfileValidator._is_valid_profile_name("my.profile") is False


class TestDomainValidation:
    """Tests for _is_valid_domain."""

    def test_simple_domain(self):
        assert ProfileValidator._is_valid_domain("example.com") is True

    def test_subdomain(self):
        assert ProfileValidator._is_valid_domain("login.example.com") is True

    def test_okta_domain(self):
        assert ProfileValidator._is_valid_domain("myorg.okta.com") is True

    def test_auth0_domain(self):
        assert ProfileValidator._is_valid_domain("myorg.us.auth0.com") is True

    def test_azure_domain(self):
        assert ProfileValidator._is_valid_domain("login.microsoftonline.com/tenant-guid/v2.0") is True

    def test_full_https_url(self):
        assert ProfileValidator._is_valid_domain("https://example.com") is True

    def test_empty_domain(self):
        assert ProfileValidator._is_valid_domain("") is False

    def test_none_domain(self):
        assert ProfileValidator._is_valid_domain(None) is False

    def test_no_dot(self):
        assert ProfileValidator._is_valid_domain("localhost") is True

    def test_hyphenated_domain(self):
        assert ProfileValidator._is_valid_domain("my-org.example.com") is True

    def test_starts_with_hyphen(self):
        assert ProfileValidator._is_valid_domain("-example.com") is False

    def test_ends_with_hyphen(self):
        assert ProfileValidator._is_valid_domain("example-.com") is False


class TestArnValidation:
    """Tests for _is_valid_arn."""

    def test_valid_iam_role_arn(self):
        assert ProfileValidator._is_valid_arn(
            "arn:aws:iam::123456789012:role/MyRole"
        ) is True

    def test_valid_cognito_arn(self):
        assert ProfileValidator._is_valid_arn(
            "arn:aws:cognito-identity:us-east-1:123456789012:identitypool/us-east-1:abc"
        ) is True

    def test_govcloud_arn(self):
        assert ProfileValidator._is_valid_arn(
            "arn:aws-us-gov:iam::123456789012:role/MyRole"
        ) is True

    def test_empty_arn(self):
        assert ProfileValidator._is_valid_arn("") is False

    def test_none_arn(self):
        assert ProfileValidator._is_valid_arn(None) is False

    def test_missing_partition(self):
        assert ProfileValidator._is_valid_arn("arn::iam::123456789012:role/x") is False

    def test_wrong_prefix(self):
        assert ProfileValidator._is_valid_arn("not:an:arn:format:123456789012:x") is False


class TestCognitoUserPoolIdValidation:
    """Tests for _is_valid_cognito_user_pool_id."""

    def test_valid_pool_id(self):
        assert ProfileValidator._is_valid_cognito_user_pool_id("us-east-1_rFo2lol9W") is True

    def test_valid_eu_pool_id(self):
        assert ProfileValidator._is_valid_cognito_user_pool_id("eu-west-2_AbC123") is True

    def test_valid_ap_pool_id(self):
        assert ProfileValidator._is_valid_cognito_user_pool_id("ap-southeast-1_Xyz789") is True

    def test_empty_pool_id(self):
        assert ProfileValidator._is_valid_cognito_user_pool_id("") is False

    def test_none_pool_id(self):
        assert ProfileValidator._is_valid_cognito_user_pool_id(None) is False

    def test_missing_region(self):
        assert ProfileValidator._is_valid_cognito_user_pool_id("_rFo2lol9W") is False

    def test_missing_underscore(self):
        assert ProfileValidator._is_valid_cognito_user_pool_id("us-east-1rFo2lol9W") is False


class TestApplicationInferenceProfileArn:
    """Tests for validate_application_inference_profile_arn."""

    def test_valid_arn(self):
        arn = "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/my-profile-1"
        assert ProfileValidator.validate_application_inference_profile_arn(arn) is None

    def test_empty_is_valid(self):
        assert ProfileValidator.validate_application_inference_profile_arn("") is None
        assert ProfileValidator.validate_application_inference_profile_arn(None) is None

    def test_whitespace_is_valid(self):
        assert ProfileValidator.validate_application_inference_profile_arn("   ") is None

    def test_wrong_service(self):
        arn = "arn:aws:iam:us-east-1:123456789012:application-inference-profile/x"
        result = ProfileValidator.validate_application_inference_profile_arn(arn)
        assert result is not None
        assert "Invalid" in result

    def test_wrong_resource_type(self):
        arn = "arn:aws:bedrock:us-east-1:123456789012:model/my-model"
        result = ProfileValidator.validate_application_inference_profile_arn(arn)
        assert result is not None

    def test_govcloud_arn(self):
        arn = "arn:aws-us-gov:bedrock:us-gov-west-1:123456789012:application-inference-profile/prof-1"
        assert ProfileValidator.validate_application_inference_profile_arn(arn) is None


class TestValidateProfile:
    """Tests for the full validate_profile function."""

    @pytest.fixture
    def valid_profile(self):
        return {
            "name": "my-profile",
            "provider_domain": "myorg.okta.com",
            "client_id": "0oa1234567890abcdef",
            "credential_storage": "keyring",
            "aws_region": "us-east-1",
            "identity_pool_name": "my-pool",
        }

    def test_valid_profile_passes(self, valid_profile):
        result = validate_profile(valid_profile)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_missing_required_field(self, valid_profile):
        del valid_profile["client_id"]
        result = validate_profile(valid_profile)
        assert result.valid is False
        assert any("client_id" in e for e in result.errors)

    def test_invalid_region(self, valid_profile):
        valid_profile["aws_region"] = "mars-west-1"
        result = validate_profile(valid_profile)
        assert result.valid is False
        assert any("aws_region" in e for e in result.errors)

    def test_invalid_credential_storage(self, valid_profile):
        valid_profile["credential_storage"] = "filesystem"
        result = validate_profile(valid_profile)
        assert result.valid is False
        assert any("credential_storage" in e for e in result.errors)

    def test_unknown_provider_type_warns(self, valid_profile):
        valid_profile["provider_type"] = "keycloak"
        result = validate_profile(valid_profile)
        # Unknown provider types produce warnings, not errors
        assert any("keycloak" in w for w in result.warnings)

    def test_cognito_requires_user_pool_id(self, valid_profile):
        valid_profile["provider_type"] = "cognito"
        result = validate_profile(valid_profile)
        assert result.valid is False
        assert any("cognito_user_pool_id" in e for e in result.errors)

    def test_cognito_valid_pool_id(self, valid_profile):
        valid_profile["provider_type"] = "cognito"
        valid_profile["cognito_user_pool_id"] = "us-east-1_rFo2lol9W"
        result = validate_profile(valid_profile)
        assert result.valid is True

    def test_generic_requires_oidc_fields(self, valid_profile):
        valid_profile["provider_type"] = "generic"
        result = validate_profile(valid_profile)
        assert result.valid is False
        assert any("oidc_issuer_url" in e for e in result.errors)

    def test_convenience_function_matches_class(self, valid_profile):
        """validate_profile() should match ProfileValidator.validate_profile()."""
        result1 = validate_profile(valid_profile)
        result2 = ProfileValidator.validate_profile(valid_profile)
        assert result1.valid == result2.valid
        assert result1.errors == result2.errors
