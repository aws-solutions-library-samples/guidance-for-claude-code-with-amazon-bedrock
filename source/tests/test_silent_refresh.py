# ABOUTME: Tests for OIDC id_token caching and silent credential refresh (issue #153)
# ABOUTME: Verifies that expired AWS credentials can be refreshed without browser popup
"""Tests for silent credential refresh using cached OIDC id_token."""

import json
import time
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest


def _make_id_token(exp_offset=3600, email="test@example.com"):
    """Create a minimal JWT id_token for testing.

    Args:
        exp_offset: Seconds from now until expiration (positive = future).
        email: Email claim to embed.
    """
    claims = {
        "sub": "user-123",
        "email": email,
        "iss": "https://test.okta.com",
        "aud": "test-client-id",
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
        "nonce": "test-nonce",
    }
    # Encode without signing (matches how the provider decodes with verify_signature=False)
    return pyjwt.encode(claims, "fake-test-jwt-key", algorithm="HS256"), claims  # pragma: allowlist secret


def _make_config():
    """Return a minimal config dict for MultiProviderAuth."""
    return {
        "profiles": {
            "TestProfile": {
                "provider_domain": "test.okta.com",
                "client_id": "test-client-id",
                "identity_pool_id": "us-east-1:test-pool",
                "aws_region": "us-east-1",
                "credential_storage": "session",
            }
        }
    }


def _make_aws_credentials(exp_offset=900):
    """Return fake AWS credentials dict."""
    from datetime import datetime, timedelta, timezone

    exp = datetime.now(timezone.utc) + timedelta(seconds=exp_offset)
    return {
        "Version": 1,
        "AccessKeyId": "FAKE-ACCESS-KEY-ID-FOR-TESTING",  # pragma: allowlist secret
        "SecretAccessKey": "fake-secret-access-key-for-testing",  # pragma: allowlist secret
        "SessionToken": "FwoGZXIvYXdzEBYaDH...",
        "Expiration": exp.isoformat(),
    }


@pytest.fixture
def auth_instance(tmp_path):
    """Create a MultiProviderAuth instance with mocked config."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(_make_config()))

    with patch("credential_provider.__main__.Path") as mock_path_cls:
        # Make _load_config find our temp config
        mock_home = MagicMock()
        mock_path_cls.home.return_value = mock_home
        mock_home.__truediv__ = lambda self, key: tmp_path / key if key == "claude-code-with-bedrock" else MagicMock()

        # Also mock __file__ parent for binary dir config lookup
        mock_file_parent = MagicMock()
        mock_file_parent.__truediv__ = lambda self, key: MagicMock(exists=lambda: False)
        mock_path_cls.return_value = mock_file_parent

        # Simpler approach: just patch _load_config and _init_credential_storage
        with (
            patch("credential_provider.__main__.MultiProviderAuth._load_config") as mock_load,
            patch("credential_provider.__main__.MultiProviderAuth._init_credential_storage"),
        ):
            mock_load.return_value = {
                "provider_domain": "test.okta.com",
                "client_id": "test-client-id",
                "identity_pool_id": "us-east-1:test-pool",
                "aws_region": "us-east-1",
                "credential_storage": "session",
                "provider_type": "okta",
                "federation_type": "cognito",
                "max_session_duration": 28800,
            }

            from credential_provider.__main__ import MultiProviderAuth

            instance = MultiProviderAuth(profile="TestProfile")
            instance.cache_dir = tmp_path / "cache"
            instance.cache_dir.mkdir(parents=True, exist_ok=True)
            return instance


class TestSilentRefresh:
    """Tests for the two-phase silent refresh (token load, then exchange)."""

    def test_silent_refresh_succeeds_with_valid_id_token(self, auth_instance):
        """When a valid id_token is cached, silent refresh should return new AWS creds."""
        id_token, claims = _make_id_token(exp_offset=3600)
        aws_creds = _make_aws_credentials()

        with (
            patch.object(auth_instance, "get_monitoring_token", return_value=id_token),
            patch.object(auth_instance, "get_aws_credentials", return_value=aws_creds) as mock_get_creds,
            patch.object(auth_instance, "save_credentials") as mock_save,
            patch.object(auth_instance, "save_monitoring_token") as mock_save_token,
        ):
            returned_token, returned_claims = auth_instance._get_cached_token_for_silent_refresh()
            assert returned_token == id_token
            assert returned_claims["sub"] == claims["sub"]

            creds = auth_instance._try_silent_refresh(returned_token, returned_claims)

            assert creds is not None
            assert creds["AccessKeyId"] == aws_creds["AccessKeyId"]
            mock_get_creds.assert_called_once()
            mock_save.assert_called_once_with(aws_creds)
            # Verify the id_token is re-persisted so the next refresh also works
            mock_save_token.assert_called_once_with(id_token, claims)

    def test_silent_refresh_returns_none_when_id_token_expired(self, auth_instance):
        """When cached id_token is within the 60-second expiry buffer, get_monitoring_token
        returns None and the token-load phase must not surface a token."""
        with (
            patch.object(auth_instance, "get_monitoring_token", return_value=None) as mock_get_token,
            patch.object(auth_instance, "get_aws_credentials") as mock_get_creds,
        ):
            id_token, token_claims = auth_instance._get_cached_token_for_silent_refresh()

            assert id_token is None
            assert token_claims is None
            mock_get_token.assert_called_once()
            # STS must never be called when the token is expired
            mock_get_creds.assert_not_called()

    def test_silent_refresh_returns_none_when_no_cached_token(self, auth_instance):
        """When no id_token is cached, the token-load phase should return None."""
        with patch.object(auth_instance, "get_monitoring_token", return_value=None):
            id_token, token_claims = auth_instance._get_cached_token_for_silent_refresh()
            assert id_token is None
            assert token_claims is None

    def test_silent_refresh_returns_none_when_sts_exchange_fails(self, auth_instance):
        """When id_token is valid but STS exchange fails, should return None (fallback to browser)."""
        id_token, claims = _make_id_token(exp_offset=3600)

        with patch.object(auth_instance, "get_aws_credentials", side_effect=Exception("STS error")):
            creds = auth_instance._try_silent_refresh(id_token, claims)
            assert creds is None

    def test_silent_refresh_not_called_when_aws_creds_valid(self, auth_instance):
        """When AWS credentials are still valid, silent refresh should not be attempted."""
        aws_creds = _make_aws_credentials(exp_offset=3600)

        with (
            patch.object(auth_instance, "get_cached_credentials", return_value=aws_creds),
            patch.object(auth_instance, "_get_cached_token_for_silent_refresh") as mock_load_token,
            patch.object(auth_instance, "_try_silent_refresh") as mock_silent,
            patch.object(auth_instance, "_should_recheck_quota", return_value=False),
        ):
            # Capture stdout
            with patch("builtins.print"):
                auth_instance.run()

            mock_load_token.assert_not_called()
            mock_silent.assert_not_called()

    def test_run_uses_silent_refresh_before_browser(self, auth_instance):
        """When AWS creds expired but id_token valid, run() should use silent refresh."""
        id_token, claims = _make_id_token(exp_offset=3600)
        aws_creds = _make_aws_credentials(exp_offset=3600)

        with (
            patch.object(auth_instance, "get_cached_credentials", return_value=None),
            patch("socket.socket") as mock_socket_cls,
            patch.object(auth_instance, "_get_cached_token_for_silent_refresh", return_value=(id_token, claims)),
            patch.object(auth_instance, "_try_silent_refresh", return_value=aws_creds),
            patch.object(auth_instance, "_should_check_quota", return_value=False),
            patch.object(auth_instance, "authenticate_oidc") as mock_browser,
            patch("builtins.print"),
        ):
            # Mock socket to simulate port available
            mock_socket = MagicMock()
            mock_socket_cls.return_value = mock_socket

            result = auth_instance.run()

            assert result == 0
            mock_browser.assert_not_called()

    def test_run_falls_back_to_browser_when_silent_refresh_fails(self, auth_instance):
        """When silent refresh fails, run() should fall back to browser auth."""
        id_token, claims = _make_id_token(exp_offset=3600)
        aws_creds = _make_aws_credentials(exp_offset=3600)

        with (
            patch.object(auth_instance, "get_cached_credentials", return_value=None),
            patch("socket.socket") as mock_socket_cls,
            patch.object(auth_instance, "_get_cached_token_for_silent_refresh", return_value=(None, None)),
            patch.object(auth_instance, "authenticate_oidc", return_value=(id_token, claims)) as mock_browser,
            patch.object(auth_instance, "_should_check_quota", return_value=False),
            patch.object(auth_instance, "get_aws_credentials", return_value=aws_creds),
            patch.object(auth_instance, "save_credentials"),
            patch.object(auth_instance, "save_monitoring_token"),
            patch("builtins.print"),
        ):
            mock_socket = MagicMock()
            mock_socket_cls.return_value = mock_socket

            result = auth_instance.run()

            assert result == 0
            mock_browser.assert_called_once()


class TestQuotaBeforeSTSOnSilentRefresh:
    """Regression tests for #761: quota must be enforced BEFORE the STS
    exchange on the silent-refresh path, so an over-quota user never mints
    or caches fresh credentials."""

    def test_quota_blocked_prevents_sts_exchange(self, auth_instance):
        """Quota blocked → run() must exit via the blocked handler WITHOUT
        calling get_aws_credentials or save_credentials. Before the fix,
        _try_silent_refresh exchanged and saved credentials first."""
        id_token, claims = _make_id_token(exp_offset=3600)

        with (
            patch.object(auth_instance, "get_cached_credentials", return_value=None),
            patch("socket.socket") as mock_socket_cls,
            patch.object(auth_instance, "get_monitoring_token", return_value=id_token),
            patch.object(auth_instance, "_should_check_quota", return_value=True),
            patch.object(auth_instance, "_check_quota", return_value={"allowed": False, "reason": "quota_exceeded"}),
            patch.object(auth_instance, "_save_quota_check_timestamp"),
            patch.object(auth_instance, "_handle_quota_blocked", return_value=1) as mock_blocked,
            patch.object(auth_instance, "get_aws_credentials") as mock_get_creds,
            patch.object(auth_instance, "save_credentials") as mock_save,
            patch.object(auth_instance, "authenticate_oidc") as mock_browser,
            patch("builtins.print"),
        ):
            mock_socket = MagicMock()
            mock_socket_cls.return_value = mock_socket

            result = auth_instance.run()

            assert result == 1
            mock_blocked.assert_called_once()
            # The heart of #761: no STS exchange, no cached credentials, no browser
            mock_get_creds.assert_not_called()
            mock_save.assert_not_called()
            mock_browser.assert_not_called()

    def test_quota_allowed_proceeds_to_sts_exchange(self, auth_instance):
        """Quota allowed → the exchange runs and credentials are emitted."""
        id_token, claims = _make_id_token(exp_offset=3600)
        aws_creds = _make_aws_credentials()

        with (
            patch.object(auth_instance, "get_cached_credentials", return_value=None),
            patch("socket.socket") as mock_socket_cls,
            patch.object(auth_instance, "get_monitoring_token", return_value=id_token),
            patch.object(auth_instance, "_should_check_quota", return_value=True),
            patch.object(auth_instance, "_check_quota", return_value={"allowed": True}) as mock_quota,
            patch.object(auth_instance, "_save_quota_check_timestamp"),
            patch.object(auth_instance, "_handle_quota_warning"),
            patch.object(auth_instance, "get_aws_credentials", return_value=aws_creds) as mock_get_creds,
            patch.object(auth_instance, "save_credentials") as mock_save,
            patch.object(auth_instance, "save_monitoring_token"),
            patch.object(auth_instance, "authenticate_oidc") as mock_browser,
            patch("builtins.print"),
        ):
            mock_socket = MagicMock()
            mock_socket_cls.return_value = mock_socket

            result = auth_instance.run()

            assert result == 0
            mock_quota.assert_called_once()
            mock_get_creds.assert_called_once()
            mock_save.assert_called_once_with(aws_creds)
            mock_browser.assert_not_called()
