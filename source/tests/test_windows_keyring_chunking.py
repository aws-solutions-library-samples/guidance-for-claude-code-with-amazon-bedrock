"""Unit tests for Windows keyring chunked monitoring token storage."""

import json
from unittest.mock import patch, MagicMock

import pytest


# We test the chunking logic by instantiating MultiProviderAuth with mocked keyring
@pytest.fixture
def auth_instance():
    """Create a MultiProviderAuth instance with mocked config for testing."""
    with patch.dict("os.environ", {}, clear=False):
        # Import here to avoid import-time side effects
        import importlib
        import sys

        # Mock keyring before importing the module
        mock_keyring = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)
        mock_keyring.set_password = MagicMock()

        with patch.dict(sys.modules, {"keyring": mock_keyring}):
            from credential_provider.__main__ import MultiProviderAuth

            config = {
                "okta_domain": "test.okta.com",
                "okta_client_id": "test-client-id",
                "aws_region": "us-east-1",
                "identity_pool_name": "test-pool",
                "credential_storage": "keyring",
                "provider_type": "okta",
            }
            auth = MultiProviderAuth.__new__(MultiProviderAuth)
            auth.config = config
            auth.profile = "TestProfile"
            auth.provider_type = "okta"
            auth._MONITORING_CHUNK_SIZE = 1200
            auth._debug_print = lambda *a, **kw: None

            yield auth, mock_keyring


class TestWindowsKeyringChunking:
    """Test the monitoring token chunked storage for Windows keyring."""

    def test_small_token_single_chunk(self, auth_instance):
        """A token shorter than chunk size should be stored as 1 chunk."""
        auth, mock_keyring = auth_instance
        token = "a" * 500  # Well under 1200 limit

        token_data = {"token": token, "expires": 9999999999, "email": "test@example.com", "profile": "TestProfile"}
        auth._save_monitoring_keyring_windows(token_data)

        calls = mock_keyring.set_password.call_args_list
        # Should have 1 chunk + 1 meta = 2 calls
        assert len(calls) == 2
        # First call: chunk 1
        assert calls[0][0] == ("claude-code-with-bedrock", "TestProfile-monitoring-1", token)
        # Second call: meta
        meta = json.loads(calls[1][0][2])
        assert meta["count"] == 1
        assert meta["expires"] == 9999999999
        assert meta["email"] == "test@example.com"

    def test_large_token_multiple_chunks(self, auth_instance):
        """A token larger than chunk size should split across multiple entries."""
        auth, mock_keyring = auth_instance
        token = "B" * 2500  # Should split into 3 chunks (1200 + 1200 + 100)

        token_data = {"token": token, "expires": 9999999999, "email": "azure@corp.com", "profile": "TestProfile"}
        auth._save_monitoring_keyring_windows(token_data)

        calls = mock_keyring.set_password.call_args_list
        # 3 chunks + 1 meta = 4 calls
        assert len(calls) == 4
        assert calls[0][0][1] == "TestProfile-monitoring-1"
        assert len(calls[0][0][2]) == 1200
        assert calls[1][0][1] == "TestProfile-monitoring-2"
        assert len(calls[1][0][2]) == 1200
        assert calls[2][0][1] == "TestProfile-monitoring-3"
        assert len(calls[2][0][2]) == 100
        # Meta
        meta = json.loads(calls[3][0][2])
        assert meta["count"] == 3

    def test_read_reassembles_chunks(self, auth_instance):
        """Reading should reassemble chunks into the original token."""
        auth, mock_keyring = auth_instance
        original_token = "C" * 2500

        # Simulate stored state
        meta = json.dumps({"count": 3, "expires": 9999999999, "email": "test@corp.com", "profile": "TestProfile"})
        chunk1 = original_token[:1200]
        chunk2 = original_token[1200:2400]
        chunk3 = original_token[2400:]

        def mock_get(service, key):
            store = {
                "TestProfile-monitoring-meta": meta,
                "TestProfile-monitoring-1": chunk1,
                "TestProfile-monitoring-2": chunk2,
                "TestProfile-monitoring-3": chunk3,
            }
            return store.get(key)

        mock_keyring.get_password = mock_get

        result = auth._read_monitoring_keyring_windows()
        assert result is not None
        assert result["token"] == original_token
        assert result["expires"] == 9999999999

    def test_read_returns_none_if_chunk_missing(self, auth_instance):
        """If any chunk is missing, read should return None (all-or-nothing)."""
        auth, mock_keyring = auth_instance

        meta = json.dumps({"count": 3, "expires": 9999999999, "email": "test@corp.com", "profile": "TestProfile"})

        def mock_get(service, key):
            store = {
                "TestProfile-monitoring-meta": meta,
                "TestProfile-monitoring-1": "chunk1data",
                # chunk 2 missing!
                "TestProfile-monitoring-3": "chunk3data",
            }
            return store.get(key)

        mock_keyring.get_password = mock_get

        result = auth._read_monitoring_keyring_windows()
        assert result is None

    def test_read_returns_none_if_no_meta(self, auth_instance):
        """If meta entry is missing, read should return None."""
        auth, mock_keyring = auth_instance
        mock_keyring.get_password = MagicMock(return_value=None)

        result = auth._read_monitoring_keyring_windows()
        assert result is None

    def test_legacy_single_entry_fallback(self, auth_instance):
        """If no chunked meta exists but legacy single entry does, should read it."""
        auth, mock_keyring = auth_instance

        legacy_data = json.dumps({"token": "legacy-token", "expires": 8888888888, "email": "old@corp.com", "profile": "TestProfile"})

        def mock_get(service, key):
            if key == "TestProfile-monitoring-meta":
                return None
            if key == "TestProfile-monitoring":
                return legacy_data
            return None

        mock_keyring.get_password = mock_get

        result = auth._read_monitoring_keyring_windows()
        # Should fall back to legacy
        assert result is not None
        assert result["token"] == "legacy-token"
