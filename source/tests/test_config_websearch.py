# ABOUTME: Contract tests for web_search_enabled + agentcore_gateway_url Profile fields
# ABOUTME: Tests AgentCore web search config persistence and backward compatibility (AC6)

"""Tests for the web_search_enabled and agentcore_gateway_url fields (AgentCore Web Search).

Encodes acceptance criterion AC6: Profile gains web_search_enabled (default False) +
agentcore_gateway_url (default ""); old configs without these fields still load.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_code_with_bedrock.config import Config, Profile


class TestWebSearchFields:
    """Tests for the web_search_enabled / agentcore_gateway_url fields in Profile."""

    def test_defaults_when_not_specified(self):
        """AC6 contract point 1: a Profile built without the new fields defaults
        web_search_enabled to False and agentcore_gateway_url to an empty string."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )

        assert profile.web_search_enabled is False
        assert profile.agentcore_gateway_url == ""

    def test_explicit_values_retained_and_serialized(self):
        """AC6 contract point 2: explicit field values are retained and to_dict()
        includes both keys with those values."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            web_search_enabled=True,
            agentcore_gateway_url="https://gw.example.com/mcp",
        )

        assert profile.web_search_enabled is True
        assert profile.agentcore_gateway_url == "https://gw.example.com/mcp"

        result = profile.to_dict()
        assert result["web_search_enabled"] is True
        assert result["agentcore_gateway_url"] == "https://gw.example.com/mcp"

    def test_from_dict_round_trips_the_fields(self):
        """AC6 contract point 3: Profile.from_dict round-trips both fields when set."""
        data = {
            "name": "test",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
            "web_search_enabled": True,
            "agentcore_gateway_url": "https://gw.example.com/mcp",
        }

        profile = Profile.from_dict(data)

        assert profile.web_search_enabled is True
        assert profile.agentcore_gateway_url == "https://gw.example.com/mcp"

    def test_backward_compatibility_from_dict_without_fields(self):
        """AC6 contract point 4 (from_dict path): a config dict lacking both fields
        loads with web_search_enabled=False and agentcore_gateway_url="", while
        other fields are preserved."""
        data = {
            "name": "default",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
            "allowed_bedrock_regions": ["us-east-1", "us-west-2"],
            "cross_region_profile": "us",
            # web_search_enabled and agentcore_gateway_url intentionally absent
        }

        profile = Profile.from_dict(data)

        assert profile.web_search_enabled is False
        assert profile.agentcore_gateway_url == ""
        # Other fields preserved
        assert profile.cross_region_profile == "us"
        assert profile.allowed_bedrock_regions == ["us-east-1", "us-west-2"]


class TestConfigManagerWithWebSearch:
    """Tests for Config save/load round-trips with the web search fields."""

    def test_backward_compatibility_without_websearch(self):
        """AC6 contract point 4 (Config.load + get_profile path): an old-style
        profile JSON on disk that lacks both fields loads via the save/load path
        with web_search_enabled=False and agentcore_gateway_url="" and other
        fields preserved. Mirrors test_backward_compatibility_without_model."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            profiles_dir = Path(tmpdir) / "profiles"
            profiles_dir.mkdir()

            config_data = {"schema_version": "2.0", "active_profile": "default", "profiles_dir": str(profiles_dir)}

            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f)

            # Old-style profile without the web search fields
            profile_data = {
                "name": "default",
                "provider_domain": "test.okta.com",
                "client_id": "test-client",
                "credential_storage": "session",
                "aws_region": "us-east-1",
                "identity_pool_name": "test-pool",
                "allowed_bedrock_regions": ["us-east-1", "us-west-2"],
                "cross_region_profile": "us",
                "monitoring_enabled": True,
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
                        assert profile.web_search_enabled is False
                        assert profile.agentcore_gateway_url == ""
                        # Other fields preserved
                        assert profile.cross_region_profile == "us"
                        assert profile.allowed_bedrock_regions == ["us-east-1", "us-west-2"]

    def test_save_and_load_with_websearch(self):
        """AC6 contract points 2+3 (full persistence path): explicit web search
        field values survive a Config save/load round-trip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"

            with patch.object(Config, "CONFIG_FILE", config_file):
                with patch.object(Config, "CONFIG_DIR", Path(tmpdir)):
                    config = Config()
                    profile = Profile(
                        name="test",
                        provider_domain="test.okta.com",
                        client_id="test-client",
                        credential_storage="keyring",
                        aws_region="us-west-2",
                        identity_pool_name="test-pool",
                        web_search_enabled=True,
                        agentcore_gateway_url="https://gw.example.com/mcp",
                    )
                    config.add_profile(profile)
                    config.save()

                    loaded_config = Config.load()
                    loaded_profile = loaded_config.get_profile("test")

                    assert loaded_profile is not None
                    assert loaded_profile.web_search_enabled is True
                    assert loaded_profile.agentcore_gateway_url == "https://gw.example.com/mcp"
