"""Tests for three bug fixes in the otel_helper and settings.json.

Fix 1 — settings.json: CLAUDE_CODE_ENABLE_TELEMETRY must NOT be hardcoded so that
         a user's env var is respected rather than overridden.

Fix 2 — read_cached_headers(): changed `if not headers:` to `if headers is None:`
         so an empty dict {} written by a failed prior run is treated as a cache *hit*
         (the caller receives {} and can decide what to do) rather than silently
         discarding it and attempting a full re-fetch.

Fix 3 — get_aws_caller_identity(): boto3 STS client must be constructed with a
         Config(connect_timeout=2, read_timeout=2, retries={'max_attempts': 0}) so
         the call fails fast instead of hanging for 4-7 s on unhealthy endpoints.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SETTINGS_JSON_PATH = (
    Path(__file__).resolve().parents[2]
    / "source"
    / "dist"
    / "claude-settings"
    / "settings.json"
)


def _reset_sts_cache():
    """Clear the module-level STS identity cache between tests."""
    import otel_helper.__main__ as mod

    mod._sts_identity_cache.clear()


# ---------------------------------------------------------------------------
# Fix 1 — settings.json must not hard-code CLAUDE_CODE_ENABLE_TELEMETRY
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not SETTINGS_JSON_PATH.exists(),
    reason="settings.json not present (requires 'poetry run ccwb package' build)",
)
class TestSettingsJsonTelemetryEnvVar:
    """settings.json must not override the user's CLAUDE_CODE_ENABLE_TELEMETRY."""

    def test_settings_json_exists(self):
        """Sanity check: the settings file must be present."""
        assert SETTINGS_JSON_PATH.exists(), (
            f"settings.json not found at {SETTINGS_JSON_PATH}"
        )

    def test_claude_code_enable_telemetry_not_in_env_block(self):
        """CLAUDE_CODE_ENABLE_TELEMETRY must be absent from the env block.

        When the key is present with a hardcoded value of '1' it silently
        overrides any user-supplied CLAUDE_CODE_ENABLE_TELEMETRY=0, making
        telemetry impossible to disable without editing the distributed file.
        """
        with open(SETTINGS_JSON_PATH) as f:
            settings = json.load(f)

        env_block = settings.get("env", {})
        assert "CLAUDE_CODE_ENABLE_TELEMETRY" not in env_block, (
            "settings.json hardcodes CLAUDE_CODE_ENABLE_TELEMETRY in the env "
            "block, which prevents users from opting out via their own env var. "
            "Remove the key so the user's environment is respected."
        )

    def test_settings_json_is_valid_json(self):
        """settings.json must parse as valid JSON (no syntax regressions)."""
        with open(SETTINGS_JSON_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_settings_json_retains_required_keys(self):
        """Core env keys required for Bedrock operation must still be present."""
        with open(SETTINGS_JSON_PATH) as f:
            settings = json.load(f)

        env_block = settings.get("env", {})
        required_keys = {"CLAUDE_CODE_USE_BEDROCK", "AWS_PROFILE"}
        missing = required_keys - env_block.keys()
        assert not missing, (
            f"Required env keys missing from settings.json: {missing}"
        )


# ---------------------------------------------------------------------------
# Fix 2 — read_cached_headers: `if headers is None` vs `if not headers`
# ---------------------------------------------------------------------------


class TestReadCachedHeadersEmptyDict:
    """read_cached_headers() must treat {} as a valid cache hit, not a miss."""

    def test_empty_dict_is_cache_hit(self, tmp_path, monkeypatch):
        """Write {} to cache; read_cached_headers must return {} not None.

        Before the fix `if not headers:` evaluated {} as falsy, returning None
        and forcing an unnecessary credential-process round-trip.
        """
        import otel_helper.__main__ as mod

        cache_file = tmp_path / "ClaudeCode-otel-headers.json"
        cache_file.write_text(json.dumps({"headers": {}, "token_exp": 9999999999, "cached_at": int(time.time())}))

        monkeypatch.setattr(mod, "get_cache_path", lambda: cache_file)

        result = mod.read_cached_headers()

        assert result is not None, (
            "read_cached_headers returned None for an empty-dict cache entry. "
            "The fix must change `if not headers:` to `if headers is None:` so "
            "that {} is treated as a cache hit."
        )
        assert result == {}, f"Expected empty dict, got {result!r}"

    def test_null_headers_is_cache_miss(self, tmp_path, monkeypatch):
        """Cache file with headers: null must still return None (true miss)."""
        import otel_helper.__main__ as mod

        cache_file = tmp_path / "ClaudeCode-otel-headers.json"
        cache_file.write_text(json.dumps({"headers": None, "token_exp": 9999999999, "cached_at": int(time.time())}))

        monkeypatch.setattr(mod, "get_cache_path", lambda: cache_file)

        result = mod.read_cached_headers()

        assert result is None, (
            f"Expected None for a null headers entry, got {result!r}"
        )

    def test_missing_headers_key_is_cache_miss(self, tmp_path, monkeypatch):
        """Cache file with no 'headers' key must return None."""
        import otel_helper.__main__ as mod

        cache_file = tmp_path / "ClaudeCode-otel-headers.json"
        cache_file.write_text(json.dumps({"token_exp": 9999999999, "cached_at": int(time.time())}))

        monkeypatch.setattr(mod, "get_cache_path", lambda: cache_file)

        result = mod.read_cached_headers()

        assert result is None, (
            f"Expected None when 'headers' key is absent, got {result!r}"
        )

    def test_nonexistent_cache_file_is_cache_miss(self, tmp_path, monkeypatch):
        """Missing cache file must return None."""
        import otel_helper.__main__ as mod

        cache_file = tmp_path / "no-such-file.json"
        monkeypatch.setattr(mod, "get_cache_path", lambda: cache_file)

        result = mod.read_cached_headers()

        assert result is None

    def test_non_empty_headers_dict_is_cache_hit(self, tmp_path, monkeypatch):
        """A normal populated headers dict must still be returned as-is."""
        import otel_helper.__main__ as mod

        headers = {"x-user-email": "alice@example.com", "x-team-id": "eng"}
        cache_file = tmp_path / "ClaudeCode-otel-headers.json"
        cache_file.write_text(json.dumps({"headers": headers, "token_exp": 9999999999, "cached_at": int(time.time())}))

        monkeypatch.setattr(mod, "get_cache_path", lambda: cache_file)

        result = mod.read_cached_headers()

        assert result == headers


class TestReadCachedHeadersRoundTrip:
    """Round-trip: write_cached_headers({}) then read_cached_headers() returns {}."""

    def test_write_empty_dict_then_read_back(self, tmp_path, monkeypatch):
        """write_cached_headers({}) followed by read_cached_headers() must return {}.

        This exercises the full persistence path and confirms that the cache file
        format survives an empty-headers write and that read treats it as a hit.
        """
        import otel_helper.__main__ as mod

        cache_file = tmp_path / "ClaudeCode-otel-headers.json"
        monkeypatch.setattr(mod, "get_cache_path", lambda: cache_file)

        # Synthetic token expiry far in the future
        token_exp = int(time.time()) + 3600
        mod.write_cached_headers({}, token_exp)

        assert cache_file.exists(), "write_cached_headers did not create the cache file"

        result = mod.read_cached_headers()

        assert result is not None, (
            "read_cached_headers returned None after writing {} to cache. "
            "Fix: change `if not headers:` to `if headers is None:`."
        )
        assert result == {}

    def test_write_populated_dict_then_read_back(self, tmp_path, monkeypatch):
        """Baseline: a populated dict round-trips correctly (regression guard)."""
        import otel_helper.__main__ as mod

        cache_file = tmp_path / "ClaudeCode-otel-headers.json"
        monkeypatch.setattr(mod, "get_cache_path", lambda: cache_file)

        headers = {"x-user-email": "bob@example.com"}
        mod.write_cached_headers(headers, int(time.time()) + 3600)

        result = mod.read_cached_headers()

        assert result == headers

    def test_write_twice_overwrites_cache_file(self, tmp_path, monkeypatch):
        """write_cached_headers must succeed on the second call when cache already exists.

        os.rename() on Windows raises FileExistsError when the destination file
        already exists (unlike POSIX which replaces atomically). Using os.replace()
        fixes this — the second write must overwrite, not silently fail.

        We simulate Windows behaviour by patching os.replace to raise
        FileExistsError on the first call, so this regression is caught on POSIX
        CI and doesn't require a Windows runner to stay green.
        """
        import os as _os
        import otel_helper.__main__ as mod  # noqa: F811 – needed for monkeypatch target

        cache_file = tmp_path / "ClaudeCode-otel-headers.json"
        monkeypatch.setattr(mod, "get_cache_path", lambda: cache_file)

        first_headers = {"x-user-email": "first@example.com"}
        second_headers = {"x-user-email": "second@example.com"}

        mod.write_cached_headers(first_headers, int(time.time()) + 3600)

        # Patch os.rename to raise FileExistsError when dest exists (Windows behavior).
        # If the code reverts to os.rename(), the second write silently fails and
        # the cache is permanently stale. os.replace() does not have this problem.
        def _windows_rename(src, dst):
            if _os.path.exists(dst):
                raise FileExistsError(f"[WinError 183] simulated: '{dst}'")
            _os.rename(src, dst)

        monkeypatch.setattr(mod.os, "rename", _windows_rename)

        mod.write_cached_headers(second_headers, int(time.time()) + 3600)

        result = mod.read_cached_headers()
        assert result == second_headers, (
            f"Cache still contains first headers after second write. "
            f"Ensure os.replace() is used instead of os.rename() so the "
            f"destination file is atomically overwritten on Windows."
        )


# ---------------------------------------------------------------------------
# Fix 3 — get_aws_caller_identity: STS client must use short timeouts
# ---------------------------------------------------------------------------


class TestGetAwsCallerIdentityTimeoutConfig:
    """get_aws_caller_identity() must pass a tight Config to boto3.client('sts')."""

    def setup_method(self):
        _reset_sts_cache()

    def teardown_method(self):
        _reset_sts_cache()

    def test_boto3_client_called_with_timeout_config(self):
        """boto3.client('sts') must receive a Config with connect_timeout=2 and read_timeout=2.

        Before the fix no Config was passed, so boto3 used its default timeouts
        (~60 s connect / no read timeout), causing a 4-7 s hang on cold starts.
        """
        import otel_helper.__main__ as mod

        mock_identity = {"Arn": "arn:aws:iam::123456789012:user/testuser", "Account": "123456789012", "UserId": "AIDATEST"}
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = mock_identity

        captured_kwargs = {}

        def fake_boto3_client(service, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_sts

        with patch("otel_helper.__main__.boto3") as mock_boto3:
            mock_boto3.client.side_effect = fake_boto3_client
            result = mod.get_aws_caller_identity()

        assert mock_boto3.client.called, "boto3.client was never called"
        call_args = mock_boto3.client.call_args

        # First positional argument must be 'sts'
        assert call_args[0][0] == "sts", (
            f"Expected boto3.client('sts', ...) but got service={call_args[0][0]!r}"
        )

        config_arg = call_args[1].get("config") or (call_args[0][1] if len(call_args[0]) > 1 else None)
        assert config_arg is not None, (
            "boto3.client('sts') was called without a 'config' keyword argument. "
            "The fix must pass Config(connect_timeout=2, read_timeout=2, retries={...})."
        )

        assert config_arg.connect_timeout == 2, (
            f"Expected connect_timeout=2, got {config_arg.connect_timeout}"
        )
        assert config_arg.read_timeout == 2, (
            f"Expected read_timeout=2, got {config_arg.read_timeout}"
        )

    def test_boto3_client_called_with_zero_retries(self):
        """STS Config must set max_attempts=0 to prevent boto3 retry delays."""
        import otel_helper.__main__ as mod

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {
            "Arn": "arn:aws:iam::123456789012:user/u",
            "Account": "123456789012",
            "UserId": "ID",
        }

        with patch("otel_helper.__main__.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_sts
            mod.get_aws_caller_identity()

        config_arg = mock_boto3.client.call_args[1].get("config")
        assert config_arg is not None

        retries = config_arg.retries
        assert retries is not None, "Config.retries must be set"
        assert retries.get("max_attempts") == 0, (
            f"Expected retries.max_attempts=0, got {retries.get('max_attempts')}"
        )

    def test_sts_timeout_returns_none_quickly(self):
        """get_aws_caller_identity() must return None quickly when STS times out.

        With the fix the total elapsed time should be well under 5 seconds
        (the mock raises immediately, so we just confirm it doesn't hang and
        returns None on exception).
        """
        import botocore.exceptions
        import otel_helper.__main__ as mod

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.side_effect = botocore.exceptions.ReadTimeoutError(endpoint_url="https://sts.amazonaws.com")

        start = time.monotonic()
        with patch("otel_helper.__main__.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_sts
            result = mod.get_aws_caller_identity()
        elapsed = time.monotonic() - start

        assert result is None, (
            f"Expected None on ReadTimeoutError, got {result!r}"
        )
        assert elapsed < 5.0, (
            f"get_aws_caller_identity took {elapsed:.2f}s after a timeout error; "
            "the fix must prevent long hangs."
        )

    def test_sts_connect_timeout_returns_none(self):
        """get_aws_caller_identity() must return None on ConnectTimeoutError."""
        import botocore.exceptions
        import otel_helper.__main__ as mod

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.side_effect = botocore.exceptions.ConnectTimeoutError(endpoint_url="https://sts.amazonaws.com")

        with patch("otel_helper.__main__.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_sts
            result = mod.get_aws_caller_identity()

        assert result is None

    def test_successful_identity_still_returned(self):
        """Sanity check: a successful STS call still returns the identity dict."""
        import otel_helper.__main__ as mod

        expected = {
            "Arn": "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_Dev_abc123/alice@example.com",
            "Account": "123456789012",
            "UserId": "AROA:alice@example.com",
        }
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = expected

        with patch("otel_helper.__main__.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_sts
            result = mod.get_aws_caller_identity()

        assert result == expected

    def test_sts_result_is_cached_on_second_call(self):
        """A second call within the TTL must use the in-memory cache, not re-call STS."""
        import otel_helper.__main__ as mod

        identity = {"Arn": "arn:aws:iam::123456789012:user/cached", "Account": "123456789012", "UserId": "ID"}
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = identity

        with patch("otel_helper.__main__.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_sts
            first = mod.get_aws_caller_identity()
            second = mod.get_aws_caller_identity()

        assert first == identity
        assert second == identity
        # boto3.client should only have been called once
        assert mock_boto3.client.call_count == 1, (
            f"Expected boto3.client to be called once due to caching, "
            f"but it was called {mock_boto3.client.call_count} times."
        )


# ---------------------------------------------------------------------------
# Fix 4 — main() must honor Claude Code's otelHeadersHelper contract on error:
# always emit a valid JSON object to stdout and exit 0, never exit 1 with empty
# stdout (which logs "otelHeadersHelper did not return a valid value" every
# export cycle). Mirrors the Go helper's emitEmptyHeaders behavior.
# ---------------------------------------------------------------------------


class TestMainErrorPathEmitsValidJson:
    """The except block in main() must print {} and return 0, not return 1."""

    def test_exception_emits_empty_json_and_exit_zero(self, capsys, monkeypatch):
        import otel_helper.__main__ as mod

        # Force a token so we take the JWT branch, then blow up inside the try.
        monkeypatch.setattr(mod, "TEST_MODE", False, raising=False)
        monkeypatch.setattr(mod, "ANONYMOUS_MODE", False, raising=False)
        monkeypatch.setenv("CLAUDE_CODE_MONITORING_TOKEN", "dummy-token")
        monkeypatch.setattr(mod, "parse_args", lambda: _ns(proxy=None, proxy_port=4318))
        monkeypatch.setattr(mod, "ensure_collector_running", lambda: None)
        monkeypatch.setattr(mod, "read_cached_headers", lambda: None)
        # Raise after the token is obtained, before any stdout is printed.
        monkeypatch.setattr(
            mod, "decode_jwt_payload", lambda _t: (_ for _ in ()).throw(ValueError("boom"))
        )

        rc = mod.main()

        assert rc == 0, "error path must exit 0 to satisfy the helper contract"
        out = capsys.readouterr().out.strip()
        assert out == "{}", f"expected empty JSON object on stdout, got: {out!r}"


def _ns(**kwargs):
    """Tiny argparse.Namespace stand-in for patching parse_args."""
    import argparse

    return argparse.Namespace(**kwargs)
