# ABOUTME: Unit tests for Profile model and configuration management
# ABOUTME: Tests cross-region profile field handling and migration logic

"""Tests for the Profile model and Config manager."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_code_with_bedrock.config import Config, Profile


class TestProfileModel:
    """Tests for the Profile dataclass."""

    def test_cross_region_profile_field_exists(self):
        """Test that cross_region_profile field is available in Profile."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            cross_region_profile="us",
        )

        assert profile.cross_region_profile == "us"
        assert "cross_region_profile" in profile.to_dict()

    def test_cross_region_profile_optional(self):
        """Test that cross_region_profile is optional and defaults to None."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )

        assert profile.cross_region_profile is None

    def test_from_dict_with_cross_region(self):
        """Test Profile.from_dict handles cross_region_profile field."""
        data = {
            "name": "test",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
            "allowed_bedrock_regions": ["us-east-1", "us-east-2", "us-west-2"],
            "cross_region_profile": "us",
            "monitoring_enabled": True,
            "analytics_enabled": True,
        }

        profile = Profile.from_dict(data)

        assert profile.cross_region_profile == "us"
        assert profile.allowed_bedrock_regions == ["us-east-1", "us-east-2", "us-west-2"]

    def test_migration_us_regions_to_cross_region_profile(self):
        """Test that existing US regions configs get 'us' cross-region profile."""
        # Legacy config without cross_region_profile but with US regions
        data = {
            "name": "legacy",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
            "allowed_bedrock_regions": ["us-west-2", "us-east-1"],
            "monitoring_enabled": False,
        }

        profile = Profile.from_dict(data)

        # Should auto-detect US profile
        assert profile.cross_region_profile == "us"

    def test_migration_non_us_regions_no_profile(self):
        """Test that non-US regions don't get auto-assigned a profile."""
        data = {
            "name": "eu-config",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "eu-west-1",
            "identity_pool_name": "test-pool",
            "allowed_bedrock_regions": ["eu-west-1", "eu-central-1"],
            "monitoring_enabled": False,
        }

        profile = Profile.from_dict(data)

        # Should not auto-assign profile for non-US regions
        assert profile.cross_region_profile is None

    def test_to_dict_includes_cross_region_profile(self):
        """Test that to_dict includes cross_region_profile."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            cross_region_profile="us",
            allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
        )

        result = profile.to_dict()

        assert result["cross_region_profile"] == "us"
        assert result["allowed_bedrock_regions"] == ["us-east-1", "us-east-2", "us-west-2"]


class TestPersonaFields:
    """Tests for the persona-based access control fields on Profile."""

    def _base_profile(self, **overrides):
        kwargs = dict(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )
        kwargs.update(overrides)
        return Profile(**kwargs)

    def test_persona_fields_default_empty(self):
        """New persona fields default to safe empty values."""
        profile = self._base_profile()

        assert profile.personas == []
        assert profile.groups_claim_name == "groups"
        assert profile.fallback_persona is None

    def test_persona_fields_settable_and_serialized(self):
        """Persona fields accept values and round-trip through to_dict."""
        personas = [
            {
                "name": "engineering",
                "group": "eng-team",
                "allowed_models": ["anthropic.*"],
                "denied_models": [],
                "enforcement_mode": "block",
            }
        ]
        profile = self._base_profile(
            personas=personas,
            groups_claim_name="cognito:groups",
            fallback_persona="engineering",
        )

        result = profile.to_dict()

        assert result["personas"] == personas
        assert result["groups_claim_name"] == "cognito:groups"
        assert result["fallback_persona"] == "engineering"

    def test_personas_are_independent_per_instance(self):
        """default_factory must not share a mutable list across instances."""
        first = self._base_profile()
        second = self._base_profile()

        first.personas.append({"name": "engineering", "group": "eng-team"})

        assert second.personas == []

    def test_from_dict_preserves_persona_fields(self):
        """Profile.from_dict round-trips the persona fields."""
        data = {
            "name": "test",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
            "personas": [{"name": "sales", "group": "sales-team", "enforcement_mode": "block"}],
            "groups_claim_name": "roles",
            "fallback_persona": "sales",
        }

        profile = Profile.from_dict(data)

        assert profile.personas == [{"name": "sales", "group": "sales-team", "enforcement_mode": "block"}]
        assert profile.groups_claim_name == "roles"
        assert profile.fallback_persona == "sales"

    def test_from_dict_old_profile_gets_empty_personas(self):
        """Pre-persona profiles load with personas=[] and default claim name."""
        data = {
            "name": "legacy",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
            "allowed_bedrock_regions": ["us-east-1"],
        }

        profile = Profile.from_dict(data)

        assert profile.personas == []
        assert profile.groups_claim_name == "groups"
        assert profile.fallback_persona is None


class TestAccountBudgetField:
    """Regression for #31 (FR-6.1): account_budget_amount_usd must be a real
    Profile field so the account-total budget is reachable through the supported
    flow. deploy.py reads getattr(profile, "account_budget_amount_usd", None);
    if it's not a field it's always None and the account budget can never deploy.
    """

    def _base(self, **extra):
        data = {
            "name": "test",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
        }
        data.update(extra)
        return data

    def test_defaults_none(self):
        profile = Profile.from_dict(self._base())
        assert profile.account_budget_amount_usd is None

    def test_round_trips_through_to_dict_and_from_dict(self):
        profile = Profile.from_dict(self._base(account_budget_amount_usd=1000.0))
        assert profile.account_budget_amount_usd == 1000.0
        # to_dict includes it; from_dict on the serialized form preserves it.
        as_dict = profile.to_dict()
        assert as_dict["account_budget_amount_usd"] == 1000.0
        round_tripped = Profile.from_dict(as_dict)
        assert round_tripped.account_budget_amount_usd == 1000.0

    def test_legacy_config_without_field_defaults_none(self):
        # A pre-#31 config.json has no account_budget_amount_usd key.
        legacy = self._base(allowed_bedrock_regions=["us-east-1"])
        profile = Profile.from_dict(legacy)
        assert profile.account_budget_amount_usd is None


class TestEffectiveAuthType:
    """Tests for the effective_auth_type property (auth-type-compat.md invariant)."""

    def _base_profile(self, **overrides):
        kwargs = dict(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )
        kwargs.update(overrides)
        return Profile(**kwargs)

    def test_sso_enabled_true_returns_oidc(self):
        """sso_enabled=True maps to 'oidc'."""
        profile = self._base_profile(sso_enabled=True)
        assert profile.effective_auth_type == "oidc"

    def test_sso_enabled_false_returns_none(self):
        """sso_enabled=False maps to 'none'."""
        profile = self._base_profile(sso_enabled=False)
        assert profile.effective_auth_type == "none"

    def test_default_profile_is_oidc(self):
        """sso_enabled defaults to True, so a default profile is 'oidc'."""
        profile = self._base_profile()
        assert profile.effective_auth_type == "oidc"

    def test_legacy_profile_without_sso_field_infers_oidc(self):
        """A pre-PR#71 profile with a real provider_domain infers sso_enabled=True -> oidc."""
        data = {
            "name": "legacy",
            "provider_domain": "company.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
        }
        profile = Profile.from_dict(data)
        assert profile.effective_auth_type == "oidc"

    def test_legacy_profile_without_provider_infers_none(self):
        """A pre-PR#71 profile with provider_domain 'none' infers sso_enabled=False -> none."""
        data = {
            "name": "legacy-no-sso",
            "provider_domain": "none",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
        }
        profile = Profile.from_dict(data)
        assert profile.effective_auth_type == "none"

    def test_auth_type_in_config_dict_is_filtered_not_honored(self):
        """An ``auth_type`` key in a loaded config is filtered by from_dict (not a field).

        Documents the L1 decision: ``auth_type`` is intentionally NOT a Profile field,
        so effective_auth_type derives purely from ``sso_enabled``. A stray ``auth_type``
        in config.json is dropped by from_dict and has no effect — which is exactly why
        a property-level "passthrough" of it would have been dead code. If first-class
        IDC support is added, ``auth_type`` must become a real dataclass field.
        """
        data = self._base_profile(sso_enabled=False).to_dict()
        data["auth_type"] = "idc"  # stray/forward-looking key
        profile = Profile.from_dict(data)
        assert not hasattr(profile, "auth_type")  # filtered by from_dict's field allowlist
        assert profile.effective_auth_type == "none"  # derived from sso_enabled only


class TestConfigManager:
    """Tests for the Config manager."""

    def test_save_and_load_with_cross_region_profile(self):
        """Test that Config properly saves and loads cross_region_profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock the config directory
            config_file = Path(tmpdir) / "config.json"

            with patch.object(Config, "CONFIG_FILE", config_file):
                with patch.object(Config, "CONFIG_DIR", Path(tmpdir)):
                    # Create and save config
                    config = Config()
                    profile = Profile(
                        name="test",
                        provider_domain="test.okta.com",
                        client_id="test-client",
                        credential_storage="keyring",
                        aws_region="us-west-2",
                        identity_pool_name="test-pool",
                        cross_region_profile="us",
                        allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
                    )
                    config.add_profile(profile)
                    config.save()

                    # Load and verify
                    loaded_config = Config.load()
                    loaded_profile = loaded_config.get_profile("test")

                    assert loaded_profile is not None
                    assert loaded_profile.cross_region_profile == "us"
                    assert loaded_profile.allowed_bedrock_regions == ["us-east-1", "us-east-2", "us-west-2"]

    def test_backward_compatibility_load(self):
        """Test loading old config files without cross_region_profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            profiles_dir = Path(tmpdir) / "profiles"
            profiles_dir.mkdir()

            # Write new-style config
            config_data = {"schema_version": "2.0", "active_profile": "default", "profiles_dir": str(profiles_dir)}

            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f)

            # Write profile without cross_region_profile (backward compatibility test)
            profile_data = {
                "name": "default",
                "provider_domain": "test.okta.com",
                "client_id": "test-client",
                "credential_storage": "session",
                "aws_region": "us-east-1",
                "identity_pool_name": "test-pool",
                "allowed_bedrock_regions": ["us-east-1", "us-west-2"],
                "monitoring_enabled": True,
                "analytics_enabled": False,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }

            with open(profiles_dir / "default.json", "w", encoding="utf-8") as f:
                json.dump(profile_data, f)

            with patch.object(Config, "CONFIG_FILE", config_file):
                with patch.object(Config, "CONFIG_DIR", Path(tmpdir)):
                    with patch.object(Config, "PROFILES_DIR", profiles_dir):
                        loaded_config = Config.load()
                        profile = loaded_config.get_profile()

                        assert profile is not None
                        # Should auto-detect US profile from regions
                        assert profile.cross_region_profile == "us"
