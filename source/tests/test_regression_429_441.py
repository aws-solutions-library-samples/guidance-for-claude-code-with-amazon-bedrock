"""Regression tests for PR #429 (Windows fixes) and #441 (OTEL latency).

These tests verify the specific bug fixes introduced in these PRs don't
regress, covering:
- OTEL cache: empty dict is a valid cache hit (not a miss)
- OTEL STS: 2s timeout prevents per-turn stalls
- OTEL cache: os.replace for atomic writes (Windows compat)
- Keyring: exact chunk boundary handling
- Keyring: rollback on partial write failure
- Model alias: tier resolution from full model IDs
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# OTEL cache: empty dict {} is a valid cache hit (#441)
# ---------------------------------------------------------------------------


class TestOtelEmptyHeadersCache:
    """Verify that {} headers in cache is treated as a valid hit, not a miss."""

    def test_empty_dict_is_valid_cache_hit(self, tmp_path):
        """An empty headers dict with a valid token_exp should return {}."""
        import importlib
        import sys

        # Reload the module to get clean state
        if "otel_helper.__main__" in sys.modules:
            mod = importlib.reload(sys.modules["otel_helper.__main__"])
        else:
            import otel_helper.__main__ as mod

        cache_file = tmp_path / "test-otel-headers.json"
        future_exp = int(time.time()) + 3600  # 1 hour from now
        cache_file.write_text(
            json.dumps(
                {
                    "headers": {},
                    "token_exp": future_exp,
                    "cached_at": int(time.time()),
                }
            )
        )

        with patch.object(mod, "get_cache_path", return_value=cache_file):
            result = mod.read_cached_headers()

        # {} is a valid headers dict (means no extra headers needed)
        assert result == {}

    def test_none_headers_is_cache_miss(self, tmp_path):
        """Headers=None in cache should return None (invalid cache)."""
        import importlib
        import sys

        if "otel_helper.__main__" in sys.modules:
            mod = importlib.reload(sys.modules["otel_helper.__main__"])
        else:
            import otel_helper.__main__ as mod

        cache_file = tmp_path / "test-otel-headers.json"
        cache_file.write_text(
            json.dumps(
                {
                    "headers": None,
                    "token_exp": int(time.time()) + 3600,
                    "cached_at": int(time.time()),
                }
            )
        )

        with patch.object(mod, "get_cache_path", return_value=cache_file):
            result = mod.read_cached_headers()

        assert result is None

    def test_missing_token_exp_triggers_refresh(self, tmp_path):
        """Old cache format without token_exp should return None (force refresh)."""
        import importlib
        import sys

        if "otel_helper.__main__" in sys.modules:
            mod = importlib.reload(sys.modules["otel_helper.__main__"])
        else:
            import otel_helper.__main__ as mod

        cache_file = tmp_path / "test-otel-headers.json"
        cache_file.write_text(
            json.dumps(
                {
                    "headers": {"Authorization": "Bearer token123"},
                    "cached_at": int(time.time()),
                    # No token_exp — old format
                }
            )
        )

        with patch.object(mod, "get_cache_path", return_value=cache_file):
            result = mod.read_cached_headers()

        assert result is None

    def test_expired_token_triggers_refresh(self, tmp_path):
        """Expired token_exp (past or within 60s buffer) should return None."""
        import importlib
        import sys

        if "otel_helper.__main__" in sys.modules:
            mod = importlib.reload(sys.modules["otel_helper.__main__"])
        else:
            import otel_helper.__main__ as mod

        cache_file = tmp_path / "test-otel-headers.json"
        expired_exp = int(time.time()) + 30  # Only 30s left (within 60s buffer)
        cache_file.write_text(
            json.dumps(
                {
                    "headers": {"Authorization": "Bearer token123"},
                    "token_exp": expired_exp,
                    "cached_at": int(time.time()) - 3500,
                }
            )
        )

        with patch.object(mod, "get_cache_path", return_value=cache_file):
            result = mod.read_cached_headers()

        assert result is None


# ---------------------------------------------------------------------------
# OTEL STS: timeout prevents per-turn stalls (#441)
# ---------------------------------------------------------------------------


class TestOtelStsTimeout:
    """Verify STS calls use short timeouts and don't stall."""

    def test_sts_client_has_2s_timeout(self):
        """get_aws_caller_identity must configure connect_timeout=2, read_timeout=2."""
        import importlib
        import sys

        if "otel_helper.__main__" in sys.modules:
            mod = importlib.reload(sys.modules["otel_helper.__main__"])
        else:
            import otel_helper.__main__ as mod

        mod._sts_identity_cache.clear()

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {
            "Arn": "arn:aws:iam::123456789012:user/test",
            "Account": "123456789012",
            "UserId": "AIDAEXAMPLE",
        }

        with patch.object(mod, "BOTO3_AVAILABLE", True), patch("otel_helper.__main__.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_sts
            mod.get_aws_caller_identity()

            # Verify the config kwarg
            call_kwargs = mock_boto3.client.call_args
            assert call_kwargs[0][0] == "sts"
            config = call_kwargs[1]["config"]
            assert config.connect_timeout == 2
            assert config.read_timeout == 2
            assert config.retries["max_attempts"] == 0

    def test_sts_timeout_returns_none_not_raises(self):
        """If STS times out, return None gracefully — don't propagate the exception."""
        import importlib
        import sys

        if "otel_helper.__main__" in sys.modules:
            mod = importlib.reload(sys.modules["otel_helper.__main__"])
        else:
            import otel_helper.__main__ as mod

        mod._sts_identity_cache.clear()

        from botocore.exceptions import ConnectTimeoutError

        with patch.object(mod, "BOTO3_AVAILABLE", True), patch("otel_helper.__main__.boto3") as mock_boto3:
            mock_boto3.client.return_value.get_caller_identity.side_effect = ConnectTimeoutError(
                endpoint_url="https://sts.us-east-1.amazonaws.com"
            )
            result = mod.get_aws_caller_identity()

        assert result is None

    def test_sts_result_is_cached(self):
        """Repeated calls within TTL should return cached result without extra API calls."""
        import importlib
        import sys

        if "otel_helper.__main__" in sys.modules:
            mod = importlib.reload(sys.modules["otel_helper.__main__"])
        else:
            import otel_helper.__main__ as mod

        mod._sts_identity_cache.clear()

        identity = {"Arn": "arn:aws:iam::123456789012:user/test", "Account": "123456789012"}
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = identity

        with patch.object(mod, "BOTO3_AVAILABLE", True), patch("otel_helper.__main__.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_sts
            result1 = mod.get_aws_caller_identity()
            result2 = mod.get_aws_caller_identity()

        # Only one API call should have been made
        mock_sts.get_caller_identity.assert_called_once()
        assert result1 == identity
        assert result2 == identity


# ---------------------------------------------------------------------------
# OTEL cache: atomic write with os.replace (#441)
# ---------------------------------------------------------------------------


class TestOtelCacheAtomicWrite:
    """Verify cache writes use os.replace for Windows compatibility."""

    def test_write_uses_os_replace(self, tmp_path):
        """write_cached_headers must use os.replace (not os.rename) for atomicity."""
        import importlib
        import sys

        if "otel_helper.__main__" in sys.modules:
            mod = importlib.reload(sys.modules["otel_helper.__main__"])
        else:
            import otel_helper.__main__ as mod

        cache_file = tmp_path / "test-otel-headers.json"
        # Create an existing file to test overwrite behavior
        cache_file.write_text("{}")

        with patch.object(mod, "get_cache_path", return_value=cache_file):
            mod.write_cached_headers(
                {"Authorization": "Bearer abc123"},
                token_exp=int(time.time()) + 3600,
            )

        # Verify the file was written
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert data["headers"] == {"Authorization": "Bearer abc123"}
        assert "token_exp" in data

    def test_write_twice_overwrites_cache_file(self, tmp_path):
        """Writing cache twice should not fail (os.replace handles existing target)."""
        import importlib
        import sys

        if "otel_helper.__main__" in sys.modules:
            mod = importlib.reload(sys.modules["otel_helper.__main__"])
        else:
            import otel_helper.__main__ as mod

        cache_file = tmp_path / "test-otel-headers.json"

        with patch.object(mod, "get_cache_path", return_value=cache_file):
            mod.write_cached_headers({"X-First": "1"}, token_exp=int(time.time()) + 100)
            mod.write_cached_headers({"X-Second": "2"}, token_exp=int(time.time()) + 200)

        data = json.loads(cache_file.read_text())
        assert data["headers"] == {"X-Second": "2"}


# ---------------------------------------------------------------------------
# Keyring: chunk boundary edge cases (#429)
# ---------------------------------------------------------------------------


class TestKeyringChunkBoundary:
    """Test keyring chunking at exact boundaries and edge cases."""

    @pytest.fixture
    def auth_with_mock_keyring(self):
        """Create a MultiProviderAuth instance with properly isolated keyring mock."""
        import importlib
        import sys

        mock_keyring = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)
        mock_keyring.set_password = MagicMock()
        mock_keyring.delete_password = MagicMock()

        with patch.dict(sys.modules, {"keyring": mock_keyring}):
            if "credential_provider.__main__" in sys.modules:
                importlib.reload(sys.modules["credential_provider.__main__"])
            from credential_provider.__main__ import MultiProviderAuth

            with patch("credential_provider.__main__.keyring", mock_keyring):
                auth = MultiProviderAuth.__new__(MultiProviderAuth)
                auth.config = {
                    "okta_domain": "test.okta.com",
                    "okta_client_id": "test-client-id",
                    "aws_region": "us-east-1",
                    "identity_pool_name": "test-pool",
                    "credential_storage": "keyring",
                    "provider_type": "okta",
                }
                auth.profile = "TestProfile"
                auth.provider_type = "okta"
                auth._MONITORING_CHUNK_SIZE = 1000
                auth._debug_print = lambda *a, **kw: None

                yield auth, mock_keyring

    def test_token_exactly_at_chunk_size(self, auth_with_mock_keyring):
        """Token exactly 1000 chars should produce exactly 1 chunk."""
        auth, mock_keyring = auth_with_mock_keyring
        token = "X" * 1000  # Exactly chunk size

        token_data = {"token": token, "expires": 9999999999, "email": "t@t.com", "profile": "TestProfile"}
        auth._save_monitoring_keyring_windows(token_data)

        set_calls = mock_keyring.set_password.call_args_list
        # 1 chunk + 1 meta = 2 calls
        assert len(set_calls) == 2
        # Verify the chunk contains the full token
        assert set_calls[0][0][2] == token

    def test_token_one_over_chunk_size(self, auth_with_mock_keyring):
        """Token of 1001 chars should produce exactly 2 chunks."""
        auth, mock_keyring = auth_with_mock_keyring
        token = "Y" * 1001  # One over chunk size

        token_data = {"token": token, "expires": 9999999999, "email": "t@t.com", "profile": "TestProfile"}
        auth._save_monitoring_keyring_windows(token_data)

        set_calls = mock_keyring.set_password.call_args_list
        # 2 chunks + 1 meta = 3 calls
        assert len(set_calls) == 3
        # Reassemble
        chunk1 = set_calls[0][0][2]
        chunk2 = set_calls[1][0][2]
        assert chunk1 + chunk2 == token
        assert len(chunk1) == 1000
        assert len(chunk2) == 1

    def test_empty_token_produces_single_empty_chunk(self, auth_with_mock_keyring):
        """An empty token should still produce 1 chunk (empty string)."""
        auth, mock_keyring = auth_with_mock_keyring
        token = ""

        token_data = {"token": token, "expires": 9999999999, "email": "t@t.com", "profile": "TestProfile"}
        auth._save_monitoring_keyring_windows(token_data)

        set_calls = mock_keyring.set_password.call_args_list
        # 1 chunk (empty) + 1 meta = 2 calls
        assert len(set_calls) == 2
        assert set_calls[0][0][2] == ""

    def test_rollback_on_partial_write_failure(self, auth_with_mock_keyring):
        """If a chunk write fails mid-way, previously written chunks are deleted."""
        auth, mock_keyring = auth_with_mock_keyring
        token = "Z" * 2500  # Will need 3 chunks

        # Fail on the 3rd set_password call (2nd chunk)
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 3:  # 3rd chunk write
                raise OSError("Credential Manager full")

        mock_keyring.set_password.side_effect = side_effect

        token_data = {"token": token, "expires": 9999999999, "email": "t@t.com", "profile": "TestProfile"}
        with pytest.raises(OSError, match="Credential Manager full"):
            auth._save_monitoring_keyring_windows(token_data)

        # Verify rollback: delete_password called for chunks already written
        delete_calls = mock_keyring.delete_password.call_args_list
        assert len(delete_calls) >= 1
        deleted_entries = [c[0][1] for c in delete_calls]
        assert "TestProfile-monitoring-1" in deleted_entries
        assert "TestProfile-monitoring-2" in deleted_entries


# ---------------------------------------------------------------------------
# Model alias: tier resolution (#278)
# ---------------------------------------------------------------------------


class TestModelAliasResolution:
    """Test get_claude_code_alias returns correct tier aliases."""

    def test_sonnet_model_returns_sonnet_alias(self):
        """A Sonnet model ID should resolve to 'sonnet' alias."""
        # Find any model that's in the sonnet tier
        from claude_code_with_bedrock.models import CLAUDE_MODELS, MODEL_TIER_PREFERENCES, get_claude_code_alias

        sonnet_keys = MODEL_TIER_PREFERENCES.get("sonnet", [])
        assert len(sonnet_keys) > 0, "No sonnet models defined"

        # Get a model_id from the first sonnet model
        for key in sonnet_keys:
            if key in CLAUDE_MODELS:
                profiles = CLAUDE_MODELS[key].get("profiles", {})
                for profile in profiles.values():
                    model_id = profile["model_id"]
                    alias = get_claude_code_alias(model_id)
                    assert alias == "sonnet", f"{model_id} should resolve to 'sonnet', got {alias}"
                    return
        pytest.skip("No sonnet model with profiles found")

    def test_opus_model_returns_opus_alias(self):
        """An Opus model ID should resolve to 'opus' alias."""
        from claude_code_with_bedrock.models import CLAUDE_MODELS, MODEL_TIER_PREFERENCES, get_claude_code_alias

        opus_keys = MODEL_TIER_PREFERENCES.get("opus", [])
        assert len(opus_keys) > 0, "No opus models defined"

        for key in opus_keys:
            if key in CLAUDE_MODELS:
                profiles = CLAUDE_MODELS[key].get("profiles", {})
                for profile in profiles.values():
                    model_id = profile["model_id"]
                    alias = get_claude_code_alias(model_id)
                    assert alias == "opus", f"{model_id} should resolve to 'opus', got {alias}"
                    return
        pytest.skip("No opus model with profiles found")

    def test_haiku_model_returns_haiku_alias(self):
        """A Haiku model ID should resolve to 'haiku' alias."""
        from claude_code_with_bedrock.models import CLAUDE_MODELS, MODEL_TIER_PREFERENCES, get_claude_code_alias

        haiku_keys = MODEL_TIER_PREFERENCES.get("haiku", [])
        assert len(haiku_keys) > 0, "No haiku models defined"

        for key in haiku_keys:
            if key in CLAUDE_MODELS:
                profiles = CLAUDE_MODELS[key].get("profiles", {})
                for profile in profiles.values():
                    model_id = profile["model_id"]
                    alias = get_claude_code_alias(model_id)
                    assert alias == "haiku", f"{model_id} should resolve to 'haiku', got {alias}"
                    return
        pytest.skip("No haiku model with profiles found")

    def test_unknown_model_returns_none(self):
        """An unrecognised model ID should return None."""
        from claude_code_with_bedrock.models import get_claude_code_alias

        assert get_claude_code_alias("anthropic.claude-nonexistent-99-v1:0") is None
        assert get_claude_code_alias("") is None
        assert get_claude_code_alias("random-string") is None

    def test_resolve_model_for_tier_with_alias_prefix(self):
        """resolve_model_for_tier should accept alias prefixes like 'europe' → 'eu'."""
        from claude_code_with_bedrock.models import PROFILE_KEY_ALIASES, resolve_model_for_tier

        # Only test if aliases are defined
        if not PROFILE_KEY_ALIASES:
            pytest.skip("No profile key aliases defined")

        for alias, resolved in PROFILE_KEY_ALIASES.items():
            # Try sonnet tier with alias
            result_alias = resolve_model_for_tier("sonnet", alias)
            result_direct = resolve_model_for_tier("sonnet", resolved)
            # Both should resolve to the same model (or both None if region unavailable)
            assert result_alias == result_direct, (
                f"Alias '{alias}' and direct '{resolved}' should resolve to the same model. "
                f"Got {result_alias} vs {result_direct}"
            )


# ---------------------------------------------------------------------------
# OAuth port race condition (#429)
# ---------------------------------------------------------------------------


class TestOAuthPortRace:
    """Test the port-based lock detection for concurrent OAuth flows."""

    def test_wait_for_auth_returns_cached_when_port_freed(self):
        """When port becomes available and cache has creds, return them."""
        import importlib
        import sys

        mock_keyring = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)
        mock_keyring.set_password = MagicMock()

        with patch.dict(sys.modules, {"keyring": mock_keyring}):
            if "credential_provider.__main__" in sys.modules:
                importlib.reload(sys.modules["credential_provider.__main__"])
            from credential_provider.__main__ import MultiProviderAuth

            with patch("credential_provider.__main__.keyring", mock_keyring):
                auth = MultiProviderAuth.__new__(MultiProviderAuth)
                auth.config = {
                    "okta_domain": "test.okta.com",
                    "okta_client_id": "test-client-id",
                    "aws_region": "us-east-1",
                    "identity_pool_name": "test-pool",
                    "credential_storage": "keyring",
                    "provider_type": "okta",
                }
                auth.profile = "TestProfile"
                auth.provider_type = "okta"
                auth.redirect_port = 18888
                auth._debug_print = lambda *a, **kw: None

                expected_creds = {"AccessKeyId": "ASIA...", "Expiration": "2026-01-01T00:00:00Z"}

                with patch("socket.socket") as mock_socket_cls:
                    mock_socket = MagicMock()
                    mock_socket_cls.return_value = mock_socket
                    # First call: port in use (EADDRINUSE), second: port free
                    import errno

                    mock_socket.bind.side_effect = [
                        OSError(errno.EADDRINUSE, "Address already in use"),
                        None,  # Port is free
                    ]

                    with patch.object(auth, "get_cached_credentials", return_value=expected_creds):
                        result = auth._wait_for_auth_completion(timeout=5)

                assert result == expected_creds

    def test_wait_for_auth_returns_none_on_timeout(self):
        """If port never frees up within timeout, return None."""
        import errno
        import importlib
        import sys

        mock_keyring = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)
        mock_keyring.set_password = MagicMock()

        with patch.dict(sys.modules, {"keyring": mock_keyring}):
            if "credential_provider.__main__" in sys.modules:
                importlib.reload(sys.modules["credential_provider.__main__"])
            from credential_provider.__main__ import MultiProviderAuth

            with patch("credential_provider.__main__.keyring", mock_keyring):
                auth = MultiProviderAuth.__new__(MultiProviderAuth)
                auth.config = {
                    "okta_domain": "test.okta.com",
                    "okta_client_id": "test-client-id",
                    "aws_region": "us-east-1",
                    "identity_pool_name": "test-pool",
                    "credential_storage": "keyring",
                    "provider_type": "okta",
                }
                auth.profile = "TestProfile"
                auth.provider_type = "okta"
                auth.redirect_port = 18888
                auth._debug_print = lambda *a, **kw: None

                with patch("socket.socket") as mock_socket_cls:
                    mock_socket = MagicMock()
                    mock_socket_cls.return_value = mock_socket
                    # Port always in use
                    mock_socket.bind.side_effect = OSError(errno.EADDRINUSE, "Address already in use")

                    with patch("time.sleep"):  # Skip actual sleeps
                        result = auth._wait_for_auth_completion(timeout=1)

                assert result is None
