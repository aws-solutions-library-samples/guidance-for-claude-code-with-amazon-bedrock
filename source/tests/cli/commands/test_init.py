# ABOUTME: Test suite for init command validation functions
# ABOUTME: Tests lambda validators and prevents regression of scoping issues

"""Test suite for init command validation functions."""

import re
import sys
from pathlib import Path

import pytest

# Imports after path setup
# ruff: noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from claude_code_with_bedrock.cli.commands.init import validate_cognito_user_pool_id, validate_identity_pool_name


class TestNamedValidationFunctions:
    """Test the named validation functions."""

    def test_validate_identity_pool_name_valid(self):
        """Test validate_identity_pool_name with valid names."""
        valid_names = ["claude-code-auth", "my_identity_pool", "test123", "UPPERCASE", "Mixed_Case-123"]

        for name in valid_names:
            result = validate_identity_pool_name(name)
            assert result is True, f"Expected '{name}' to be valid, but got: {result}"

    def test_validate_identity_pool_name_invalid(self):
        """Test validate_identity_pool_name with invalid names."""
        invalid_names = ["", "pool name with spaces", "pool.with.dots", "pool@with#special$chars"]

        for name in invalid_names:
            result = validate_identity_pool_name(name)
            assert (
                result == "Invalid name (alphanumeric, underscore, hyphen only)"
            ), f"Expected '{name}' to be invalid, but got: {result}"

    def test_validate_cognito_user_pool_id_valid(self):
        """Test validate_cognito_user_pool_id with valid IDs."""
        valid_ids = ["us-east-1_abc123XYZ", "eu-west-2_9876543210", "ap-southeast-1_ABCdefGHI"]

        for pool_id in valid_ids:
            result = validate_cognito_user_pool_id(pool_id)
            assert result is True, f"Expected '{pool_id}' to be valid, but got: {result}"

    def test_validate_cognito_user_pool_id_invalid(self):
        """Test validate_cognito_user_pool_id with invalid IDs."""
        invalid_ids = ["", "noUnderscore", "endswith_", "special@chars_123"]

        for pool_id in invalid_ids:
            result = validate_cognito_user_pool_id(pool_id)
            assert result == "Invalid User Pool ID format", f"Expected '{pool_id}' to be invalid, but got: {result}"


class TestInitCommandValidation:
    """Test validation functions in the init command (lambda compatibility)."""

    def test_identity_pool_name_validator_valid_names(self):
        """Test that valid identity pool names pass validation."""

        # Extract the validator from line 352
        # The validator validates alphanumeric, underscore, hyphen only
        def validator(x):
            error_msg = "Invalid name (alphanumeric, underscore, hyphen only)"
            return bool(x and re.match(r"^[a-zA-Z0-9_-]+$", x)) or error_msg

        valid_names = [
            "claude-code-auth",
            "my_identity_pool",
            "test123",
            "UPPERCASE",
            "Mixed_Case-123",
            "a",
            "1",
            "_underscore",
            "-hyphen",
            "very_long_name_with_many_characters_123456789",
        ]

        for name in valid_names:
            result = validator(name)
            assert result is True, f"Expected '{name}' to be valid, but got: {result}"

    def test_identity_pool_name_validator_invalid_names(self):
        """Test that invalid identity pool names fail validation."""

        def validator(x):
            error_msg = "Invalid name (alphanumeric, underscore, hyphen only)"
            return bool(x and re.match(r"^[a-zA-Z0-9_-]+$", x)) or error_msg

        invalid_names = [
            "",  # Empty string
            None,  # None value
            "pool name with spaces",
            "pool.with.dots",
            "pool/with/slashes",
            "pool@with#special$chars",
            "pool名with中文",
            "pool\nwith\nnewlines",
            "pool\twith\ttabs",
        ]

        for name in invalid_names:
            result = validator(name)
            assert (
                result == "Invalid name (alphanumeric, underscore, hyphen only)"
            ), f"Expected '{name}' to be invalid, but got: {result}"

    def test_cognito_user_pool_id_validator_valid_ids(self):
        """Test that valid Cognito User Pool IDs pass validation."""

        # The validator is: lambda x: bool(re.match(r'^[\w-]+_[0-9a-zA-Z]+$', x)) or "Invalid User Pool ID format"
        def validator(x):
            return bool(re.match(r"^[\w-]+_[0-9a-zA-Z]+$", x)) or "Invalid User Pool ID format"

        valid_ids = [
            "us-east-1_abc123XYZ",
            "eu-west-2_9876543210",
            "ap-southeast-1_ABCdefGHI",
            "us-west-2_a1b2c3d4e5",
            "region_pool123",
            "test-region_ID999",
            "a_1",
            "simple_test",
        ]

        for pool_id in valid_ids:
            result = validator(pool_id)
            assert result is True, f"Expected '{pool_id}' to be valid, but got: {result}"

    def test_cognito_user_pool_id_validator_invalid_ids(self):
        """Test that invalid Cognito User Pool IDs fail validation."""

        def validator(x):
            return bool(re.match(r"^[\w-]+_[0-9a-zA-Z]+$", x)) or "Invalid User Pool ID format"

        invalid_ids = [
            "",  # Empty string
            "noUnderscore",  # Missing underscore separator
            "_startswith",  # Starts with underscore
            "endswith_",  # Ends with underscore
            "special@chars_123",  # Special characters before underscore
            "region_pool-with-hyphen",  # Hyphen after underscore
            "region_",  # No ID after underscore
            "_pool123",  # No region before underscore
            "region pool_123",  # Space in region
            "region_pool 123",  # Space in ID
            "region_pool_with_special@",  # Special character after underscore
            "region.pool_123",  # Dot in region part
        ]

        for pool_id in invalid_ids:
            result = validator(pool_id)
            assert result == "Invalid User Pool ID format", f"Expected '{pool_id}' to be invalid, but got: {result}"

    def test_regex_module_available_in_scope(self):
        """Test that the regex module is available and not causing scoping issues."""
        # This test verifies that we can access the re module without issues
        # simulating what happens in the actual lambda functions

        def simulate_lambda_scope():
            """Simulate the lambda function scope to ensure re is accessible."""

            # This simulates the lambda on line 352
            def identity_validator(x):
                error_msg = "Invalid name (alphanumeric, underscore, hyphen only)"
                return bool(x and re.match(r"^[a-zA-Z0-9_-]+$", x)) or error_msg

            # This simulates the lambda on line 275
            def cognito_validator(x):
                return bool(re.match(r"^[\w-]+_[0-9a-zA-Z]+$", x)) or "Invalid User Pool ID format"

            # Test both validators
            assert identity_validator("test-pool") is True
            assert cognito_validator("us-east-1_abc123") is True

            return True

        # This should not raise any exceptions about accessing free variable 're'
        assert simulate_lambda_scope() is True

    def test_regex_patterns_correctness(self):
        """Test that the regex patterns themselves are correct and compilable."""
        # Test identity pool name pattern
        identity_pattern = r"^[a-zA-Z0-9_-]+$"
        assert re.compile(identity_pattern), "Identity pool name pattern should compile"

        # Test Cognito User Pool ID pattern
        cognito_pattern = r"^[\w-]+_[0-9a-zA-Z]+$"
        assert re.compile(cognito_pattern), "Cognito User Pool ID pattern should compile"

    def test_edge_cases(self):
        """Test edge cases for both validators."""

        def identity_validator(x):
            return (
                bool(x and re.match(r"^[a-zA-Z0-9_-]+$", x))
                or "Invalid name (alphanumeric, underscore, hyphen only)"
            )

        def cognito_validator(x):
            return bool(re.match(r"^[\w-]+_[0-9a-zA-Z]+$", x)) or "Invalid User Pool ID format"

        # Test very long valid strings
        long_identity = "a" * 1000
        assert identity_validator(long_identity) is True

        long_cognito = "a" * 500 + "_" + "b" * 500
        assert cognito_validator(long_cognito) is True

        # Test single character cases
        assert identity_validator("a") is True
        assert identity_validator("1") is True
        assert identity_validator("_") is True
        assert identity_validator("-") is True

        # Test minimum valid Cognito ID
        assert cognito_validator("a_1") is True
        assert cognito_validator("1_a") is True


class TestCognitoRegionDetection:
    """Test that Cognito region detection works correctly with re module."""

    def test_cognito_region_extraction_from_domain(self):
        """Test that region can be extracted from Cognito domains."""
        # Test standard Cognito domain format
        test_cases = [
            ("myapp.auth.us-east-1.amazoncognito.com", "us-east-1"),
            ("custom.auth.eu-west-2.amazoncognito.com", "eu-west-2"),
            ("test.auth.ap-southeast-1.amazoncognito.com", "ap-southeast-1"),
        ]

        for domain, expected_region in test_cases:
            # This is the same regex used in init.py line 281
            region_match = re.search(r"\.auth\.([^.]+)\.amazoncognito\.com", domain)
            assert region_match is not None, f"Failed to match region in {domain}"
            assert region_match.group(1) == expected_region, f"Expected {expected_region}, got {region_match.group(1)}"

    def test_cognito_region_fallback_pattern(self):
        """Test the fallback region pattern for non-standard domains."""
        # Test fallback pattern for custom domains
        test_cases = [
            ("custom.us-west-2.example.com", "us-west-2"),
            ("app.eu-central-1.customdomain.com", "eu-central-1"),
            ("service.ap-south-1.internal.com", "ap-south-1"),
        ]

        for domain, expected_region in test_cases:
            # This is the fallback regex used in init.py line 283
            region_match = re.search(r"\.([a-z]{2}-[a-z]+-\d+)\.", domain)
            assert region_match is not None, f"Failed to match region in {domain}"
            assert region_match.group(1) == expected_region, f"Expected {expected_region}, got {region_match.group(1)}"

    def test_region_detection_with_actual_init_code(self):
        """Test that the actual region detection code path works after our fix."""
        # Simulate the exact code path from init.py
        provider_domain = "myapp.auth.us-east-1.amazoncognito.com"

        # Lines 281-283 from init.py
        region_match = re.search(r"\.auth\.([^.]+)\.amazoncognito\.com", provider_domain)
        if not region_match:
            region_match = re.search(r"\.([a-z]{2}-[a-z]+-\d+)\.", provider_domain)

        assert region_match is not None, "Region detection failed completely"
        assert region_match.group(1) == "us-east-1", f"Wrong region extracted: {region_match.group(1)}"

        # Test with a custom domain that needs fallback
        provider_domain = "custom.us-west-2.mydomain.com"
        region_match = re.search(r"\.auth\.([^.]+)\.amazoncognito\.com", provider_domain)
        if not region_match:
            region_match = re.search(r"\.([a-z]{2}-[a-z]+-\d+)\.", provider_domain)

        assert region_match is not None, "Fallback region detection failed"
        assert region_match.group(1) == "us-west-2", f"Wrong region extracted: {region_match.group(1)}"


class TestInitCommandRegression:
    """Regression tests to prevent the lambda scoping issue from recurring."""

    def test_no_duplicate_imports(self):
        """Ensure there are no duplicate import statements for 're' module."""
        init_file_path = (
            Path(__file__).parent.parent.parent.parent / "claude_code_with_bedrock" / "cli" / "commands" / "init.py"
        )

        with open(init_file_path, encoding="utf-8") as f:
            content = f.read()

        # Count occurrences of 'import re'
        import_count = content.count("import re")

        # There should be exactly one import at the module level
        assert import_count == 1, f"Found {import_count} 'import re' statements, expected 1"

        # Make sure the import is at the top of the file (in the first 500 characters)
        assert "import re" in content[:500], "The 'import re' should be at the top of the file"

    def test_lambda_functions_can_access_re(self):
        """Test that all lambda functions in init.py can access the re module."""
        # This test creates the actual lambda functions from the file
        # to ensure they can access 're' without scoping issues

        # Import the module fresh to test current state
        import importlib

        import claude_code_with_bedrock.cli.commands.init as init_module

        importlib.reload(init_module)

        # The lambdas should be able to execute without raising exceptions
        # We test this by creating similar lambdas here
        test_lambdas = [
            lambda x: bool(x and re.match(r"^[a-zA-Z0-9_-]+$", x))
            or "Invalid name (alphanumeric, underscore, hyphen only)",
            lambda x: bool(re.match(r"^[\w-]+_[0-9a-zA-Z]+$", x)) or "Invalid User Pool ID format",
        ]

        # Execute each lambda to ensure no scoping errors
        for i, test_lambda in enumerate(test_lambdas):
            try:
                result = test_lambda("test_value_123")
                assert result is True, f"Lambda {i} should validate 'test_value_123' as True"
            except NameError as e:
                pytest.fail(f"Lambda {i} raised NameError: {e}. This indicates a scoping issue with 're' module.")


class TestCrossRegionProfiles:
    """Test cross-region profile configuration."""

    def test_cross_region_profile_sets_correct_regions(self):
        """Test that US cross-region profile sets correct regions."""
        # Define the expected profile (matching what's in init.py)
        CROSS_REGION_PROFILES = {
            "us": {
                "name": "US Cross-Region",
                "regions": ["us-east-1", "us-east-2", "us-west-2"],
                "description": "Routes across US regions (N. Virginia, Ohio, Oregon)",
            }
        }

        # Test that selecting 'us' profile sets the right regions
        profile_info = CROSS_REGION_PROFILES["us"]
        assert profile_info["regions"] == ["us-east-1", "us-east-2", "us-west-2"]
        assert "US Cross-Region" in profile_info["name"]

    def test_cross_region_profile_in_config(self):
        """Test that cross_region_profile is saved in configuration."""
        from claude_code_with_bedrock.config import Profile

        # Create a profile with cross-region settings
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
            cross_region_profile="us",
        )

        # Verify the profile has cross-region settings
        assert profile.cross_region_profile == "us"
        assert len(profile.allowed_bedrock_regions) == 3
        assert "us-east-1" in profile.allowed_bedrock_regions
        assert "us-east-2" in profile.allowed_bedrock_regions
        assert "us-west-2" in profile.allowed_bedrock_regions

    def test_future_cross_region_profiles_structure(self):
        """Test that the structure supports future cross-region profiles."""
        # Example of how future profiles would be added
        FUTURE_PROFILES = {
            "us": {
                "name": "US Cross-Region",
                "regions": ["us-east-1", "us-east-2", "us-west-2"],
                "description": "Routes across US regions",
            },
            "eu": {
                "name": "EU Cross-Region",
                "regions": ["eu-west-1", "eu-west-2", "eu-central-1"],
                "description": "Routes across European regions",
            },
            "global": {
                "name": "Global Cross-Region",
                "regions": ["us-east-1", "us-east-2", "us-west-2", "eu-west-1", "ap-southeast-1"],
                "description": "Routes globally for maximum availability",
            },
        }

        # Verify structure is consistent
        for _profile_key, profile_data in FUTURE_PROFILES.items():
            assert "name" in profile_data
            assert "regions" in profile_data
            assert "description" in profile_data
            assert isinstance(profile_data["regions"], list)
            assert len(profile_data["regions"]) > 0


class TestNamedFunctionsIntegration:
    """Integration tests for named validation functions."""

    def test_functions_work_with_questionary(self):
        """Test that the named functions work correctly with questionary."""
        # The functions should return exactly True or an error string
        # This is what questionary expects

        # Valid cases should return True (not truthy values)
        assert validate_identity_pool_name("valid-name") is True
        assert validate_cognito_user_pool_id("us-east-1_abc123") is True

        # Invalid cases should return the error string
        assert isinstance(validate_identity_pool_name(""), str)
        assert isinstance(validate_cognito_user_pool_id(""), str)

    def test_functions_are_imported_correctly(self):
        """Test that the functions are properly exported from the module."""
        from claude_code_with_bedrock.cli.commands import init as init_module

        assert hasattr(init_module, "validate_identity_pool_name")
        assert hasattr(init_module, "validate_cognito_user_pool_id")
        assert callable(init_module.validate_identity_pool_name)
        assert callable(init_module.validate_cognito_user_pool_id)


class TestSsoDisabledRendering:
    """Regression tests for issue #430.

    Ensure the wizard does not crash with KeyError: 'okta' when SSO is
    disabled. The okta key is only populated by the OIDC flow, so methods
    that render or persist it must guard against its absence.
    """

    @pytest.fixture
    def cmd(self):
        from claude_code_with_bedrock.cli.commands.init import InitCommand
        return InitCommand()

    @pytest.fixture
    def base_aws(self):
        return {
            "region": "us-east-1",
            "identity_pool_name": "demo-pool",
            "allowed_bedrock_regions": ["us-east-1"],
            "stacks": {},
        }

    def test_review_configuration_without_okta_key_does_not_raise(self, cmd, base_aws):
        config = {
            "sso_enabled": False,
            "credential_storage": "session",
            "aws": base_aws,
            "monitoring": {"enabled": False},
        }
        # Must not raise KeyError: 'okta'
        assert cmd._review_configuration(config) is True

    def test_review_configuration_sso_enabled_still_renders_okta(self, cmd, base_aws):
        config = {
            "sso_enabled": True,
            "okta": {"domain": "company.okta.com", "client_id": "abcdef1234567890abcdef"},
            "credential_storage": "keyring",
            "aws": base_aws,
            "monitoring": {"enabled": False},
        }
        assert cmd._review_configuration(config) is True

    def test_show_existing_deployment_without_okta_key_does_not_raise(self, cmd, base_aws):
        config = {
            "sso_enabled": False,
            "aws": base_aws,
            "monitoring": {"enabled": False},
        }
        # Must not raise KeyError: 'okta'
        cmd._show_existing_deployment(config)

    def test_update_parameters_file_without_okta_key_writes_none(self, cmd, base_aws, tmp_path):
        import json

        params_file = tmp_path / "params.json"
        config = {
            "sso_enabled": False,
            "aws": base_aws,
            "monitoring": {"enabled": False},
        }
        cmd._update_parameters_file(params_file, config)

        with open(params_file) as f:
            params = json.load(f)
        param_map = {p["ParameterKey"]: p["ParameterValue"] for p in params}
        assert param_map["OktaDomain"] == "none"
        assert param_map["OktaClientId"] == "none"

    def test_review_configuration_with_empty_okta_dict_does_not_raise(self, cmd, base_aws):
        """Edge case: SSO enabled but the user cancelled before entering a domain.

        Config can end up with `okta: {}`. The defensive .get() chain must
        handle this without raising KeyError on missing 'domain' / 'client_id'.
        """
        config = {
            "sso_enabled": True,
            "okta": {},  # OIDC flow started but cancelled before fields were set
            "credential_storage": "session",
            "aws": base_aws,
            "monitoring": {"enabled": False},
        }
        assert cmd._review_configuration(config) is True

    def test_save_configuration_sso_disabled_creates_profile(self, cmd, base_aws, tmp_path):
        """_save_configuration must create a valid Profile when SSO is disabled.

        The Profile dataclass has required fields (provider_domain, client_id)
        that must be populated with sensible defaults when no OIDC flow ran.
        """
        import json
        from unittest.mock import patch
        from claude_code_with_bedrock.config import Config

        config_data = {
            "sso_enabled": False,
            "aws": {
                **base_aws,
                "cross_region_profile": "us",
                "selected_model": None,
            },
            "monitoring": {"enabled": False},
            "credential_storage": "session",
        }

        config_dir = tmp_path / ".ccwb"
        config_dir.mkdir()
        profiles_dir = config_dir / "profiles"
        profiles_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({"schema_version": "2.0", "active_profile": None}))

        with patch.object(Config, "CONFIG_DIR", config_dir), \
             patch.object(Config, "CONFIG_FILE", config_file), \
             patch.object(Config, "PROFILES_DIR", profiles_dir):
            # Must not raise KeyError or TypeError
            cmd._save_configuration(config_data, "test-no-sso")

            # Verify the saved profile has sensible defaults
            profile_file = profiles_dir / "test-no-sso.json"
            assert profile_file.exists()
            saved = json.loads(profile_file.read_text())
            assert saved["provider_domain"] == "none"
            assert saved["client_id"] == "none"
            assert saved["sso_enabled"] is False

    def test_save_configuration_round_trip_preserves_sso_enabled(self, cmd, base_aws, tmp_path):
        """A profile saved with sso_enabled=False must reload with sso_enabled=False.

        Regression guard: if the field isn't persisted, re-running ccwb init
        on an existing deployment could flip sso_enabled back to True (the default),
        which would re-enable the auth stack and break the deployment.
        """
        import json
        from unittest.mock import patch
        from claude_code_with_bedrock.config import Config

        config_data = {
            "sso_enabled": False,
            "aws": {
                **base_aws,
                "cross_region_profile": "us",
                "selected_model": None,
            },
            "monitoring": {"enabled": False},
            "credential_storage": "session",
        }

        config_dir = tmp_path / ".ccwb"
        config_dir.mkdir()
        profiles_dir = config_dir / "profiles"
        profiles_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({"schema_version": "2.0", "active_profile": "test-roundtrip"}))

        with patch.object(Config, "CONFIG_DIR", config_dir), \
             patch.object(Config, "CONFIG_FILE", config_file), \
             patch.object(Config, "PROFILES_DIR", profiles_dir):
            cmd._save_configuration(config_data, "test-roundtrip")

            # Reload from disk
            reloaded = Config.load()
            profile = reloaded.get_profile("test-roundtrip")
            assert profile is not None
            assert profile.sso_enabled is False
            assert profile.provider_domain == "none"

    def test_update_parameters_file_sso_enabled_uses_real_values(self, cmd, base_aws, tmp_path):
        """When SSO is enabled, OktaDomain/OktaClientId must use real values (not 'none').

        Prevents a regression where the sso_enabled guard is inverted or
        the .get() chain defaults mask a real configuration.
        """
        import json

        params_file = tmp_path / "params.json"
        config = {
            "sso_enabled": True,
            "okta": {"domain": "company.okta.com", "client_id": "abc123xyz"},
            "aws": base_aws,
            "monitoring": {"enabled": False},
        }
        cmd._update_parameters_file(params_file, config)

        with open(params_file) as f:
            params = json.load(f)
        param_map = {p["ParameterKey"]: p["ParameterValue"] for p in params}
        assert param_map["OktaDomain"] == "company.okta.com"
        assert param_map["OktaClientId"] == "abc123xyz"


class TestLandingPageRegionResolution:
    """Regression tests for region UnboundLocalError on the skip_aws landing-page path.

    When AWS setup is skipped (last_step in aws_complete/monitoring_complete/
    bedrock_complete with no existing_config), `region` is never assigned by the
    AWS-setup block. The landing-page distribution block still runs and uses
    `region` for Cognito detection AND for the Secrets Manager client. Every IdP
    provider (okta/azure/auth0/cognito/google) must resolve `region` from saved
    config instead of crashing with UnboundLocalError.

    The original fix (commit c314ada) only bound `region` inside the
    `if idp_provider == "cognito":` branch, so the four non-cognito providers
    still crashed. This guards all five.
    """

    class _StopAfterSecrets(Exception):
        """Raised at the custom-domain prompt, downstream of the secrets block."""

    def _run_landing_page(self, idp_provider):
        """Drive _gather_configuration down the skip_aws landing-page path.

        Returns the region_name passed to boto3's secretsmanager client.
        Raises UnboundLocalError if the bug is present.
        """
        from unittest.mock import MagicMock, patch

        import questionary

        from claude_code_with_bedrock.cli.commands.init import InitCommand

        # last_step="bedrock_complete" -> skip_okta/skip_aws/skip_monitoring/skip_bedrock
        # all True, so the only prompts before the secrets block are distribution + IdP fields.
        progress = MagicMock()
        progress.get_last_step.return_value = "bedrock_complete"
        progress.get_saved_data.return_value = {
            "sso_enabled": False,
            "auth_type": "none",
            "aws": {"region": "ap-southeast-1", "identity_pool_name": "claude-code-auth"},
        }

        def fake_select(message, *a, **k):
            m = MagicMock()
            text = str(message)
            if "Distribution method" in text:
                m.ask.return_value = "landing-page"
            elif "Identity provider" in text:
                m.ask.return_value = idp_provider
            else:
                m.ask.return_value = None
            return m

        def fake_text(message, *a, **k):
            m = MagicMock()
            if "Custom domain" in str(message):
                # We've passed the secrets block (line ~1336); stop deterministically.
                m.ask.side_effect = self._StopAfterSecrets
            else:
                m.ask.return_value = "dummy.example.com"
            return m

        def fake_password(*a, **k):
            m = MagicMock()
            m.ask.return_value = "dummy-secret"
            return m

        def fake_confirm(*a, **k):
            m = MagicMock()
            m.ask.return_value = False
            return m

        captured = {}

        def spy_client(name, *a, **k):
            if name == "secretsmanager":
                captured["region_name"] = k.get("region_name")
            return MagicMock()

        cmd = InitCommand()
        with patch.object(questionary, "select", fake_select), \
             patch.object(questionary, "text", fake_text), \
             patch.object(questionary, "password", fake_password), \
             patch.object(questionary, "confirm", fake_confirm), \
             patch("boto3.client", spy_client):
            try:
                cmd._gather_configuration(progress)
            except self._StopAfterSecrets:
                pass
        return captured.get("region_name")

    @pytest.mark.parametrize("idp_provider", ["okta", "azure", "auth0", "cognito", "google"])
    def test_region_bound_for_all_providers_when_aws_skipped(self, idp_provider):
        """region must resolve from saved config for every IdP provider, not crash."""
        # Pre-fix: raises UnboundLocalError for okta/azure/auth0/google.
        region_name = self._run_landing_page(idp_provider)
        assert region_name == "ap-southeast-1"


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])
