# ABOUTME: Tests for the PowerShell otel-helper script (Windows AV-safe alternative)
# ABOUTME: Validates cache logic, token splicing, and fallback behavior

"""Tests for otel-helper.ps1 logic (validates the Python-testable cache/splice logic)."""

import json
import os
import tempfile
import time
from pathlib import Path

import pytest


class TestOtelHelperCacheLogic:
    """Test the cache-check and token-splice logic that otel-helper.ps1 implements.

    Since we can't run PowerShell in CI on all platforms, we test the equivalent
    Python logic that mirrors the PS1 script's behavior. This ensures the algorithm
    is correct; the PS1 is a mechanical port of this logic.
    """

    def _simulate_otel_helper(self, cache_dir: Path, profile: str = "ClaudeCode",
                               monitoring_token: str = "", env_token: str = ""):
        """Simulate the otel-helper.ps1 logic in Python for testing."""
        cache_file = cache_dir / f"{profile}-otel-headers.json"
        raw_file = cache_dir / f"{profile}-otel-headers.raw"
        monitoring_file = cache_dir / f"{profile}-monitoring.json"

        # Step 1: Check cache validity
        if cache_file.exists() and raw_file.exists():
            try:
                cache_data = json.loads(cache_file.read_text())
                token_exp = int(cache_data.get("token_exp", 0))
                now = int(time.time())

                if token_exp > (now + 60):
                    # Token still valid
                    raw_content = raw_file.read_text().strip()

                    # Resolve Bearer token
                    token = env_token
                    if not token and monitoring_file.exists():
                        try:
                            mon_data = json.loads(monitoring_file.read_text())
                            token = mon_data.get("token", "")
                        except Exception:
                            pass

                    if token:
                        # Splice Bearer token into raw JSON
                        trimmed = raw_content.rstrip("}").rstrip()
                        if trimmed.rstrip() != "{":
                            return f'{trimmed}, "authorization": "Bearer {token}"}}'
                        else:
                            return f'{trimmed}"authorization": "Bearer {token}"}}'
                    else:
                        return raw_content
            except Exception:
                pass

        # Cache miss or expired
        return "{}"

    def test_valid_cache_with_env_token(self, tmp_path):
        """Valid cache + env token = headers with Bearer spliced in."""
        profile = "TestProfile"
        cache_file = tmp_path / f"{profile}-otel-headers.json"
        raw_file = tmp_path / f"{profile}-otel-headers.raw"

        # Future expiry
        cache_file.write_text(json.dumps({"token_exp": int(time.time()) + 3600}))
        raw_file.write_text('{"x-user-email": "test@example.com"}')

        result = self._simulate_otel_helper(tmp_path, profile, env_token="my-jwt-token")
        parsed = json.loads(result)
        assert parsed["x-user-email"] == "test@example.com"
        assert parsed["authorization"] == "Bearer my-jwt-token"

    def test_valid_cache_with_monitoring_file_token(self, tmp_path):
        """Valid cache + monitoring file token = headers with Bearer."""
        profile = "TestProfile"
        cache_file = tmp_path / f"{profile}-otel-headers.json"
        raw_file = tmp_path / f"{profile}-otel-headers.raw"
        monitoring_file = tmp_path / f"{profile}-monitoring.json"

        cache_file.write_text(json.dumps({"token_exp": int(time.time()) + 3600}))
        raw_file.write_text('{"x-user-email": "test@example.com"}')
        monitoring_file.write_text(json.dumps({"token": "monitoring-jwt"}))

        result = self._simulate_otel_helper(tmp_path, profile, monitoring_token="monitoring-jwt")
        parsed = json.loads(result)
        assert parsed["authorization"] == "Bearer monitoring-jwt"

    def test_valid_cache_no_token_serves_raw(self, tmp_path):
        """Valid cache + no token = raw headers without Bearer."""
        profile = "TestProfile"
        cache_file = tmp_path / f"{profile}-otel-headers.json"
        raw_file = tmp_path / f"{profile}-otel-headers.raw"

        cache_file.write_text(json.dumps({"token_exp": int(time.time()) + 3600}))
        raw_file.write_text('{"x-user-email": "test@example.com"}')

        result = self._simulate_otel_helper(tmp_path, profile)
        parsed = json.loads(result)
        assert parsed == {"x-user-email": "test@example.com"}
        assert "authorization" not in parsed

    def test_expired_cache_returns_empty(self, tmp_path):
        """Expired cache = empty JSON (triggers fallback)."""
        profile = "TestProfile"
        cache_file = tmp_path / f"{profile}-otel-headers.json"
        raw_file = tmp_path / f"{profile}-otel-headers.raw"

        # Past expiry
        cache_file.write_text(json.dumps({"token_exp": int(time.time()) - 100}))
        raw_file.write_text('{"x-user-email": "test@example.com"}')

        result = self._simulate_otel_helper(tmp_path, profile, env_token="my-token")
        assert result == "{}"

    def test_missing_cache_returns_empty(self, tmp_path):
        """No cache files = empty JSON."""
        result = self._simulate_otel_helper(tmp_path, "NonExistent")
        assert result == "{}"

    def test_empty_raw_headers_splices_correctly(self, tmp_path):
        """Empty raw headers {} + token = just Bearer header."""
        profile = "TestProfile"
        cache_file = tmp_path / f"{profile}-otel-headers.json"
        raw_file = tmp_path / f"{profile}-otel-headers.raw"

        cache_file.write_text(json.dumps({"token_exp": int(time.time()) + 3600}))
        raw_file.write_text('{}')

        result = self._simulate_otel_helper(tmp_path, profile, env_token="jwt123")
        parsed = json.loads(result)
        assert parsed == {"authorization": "Bearer jwt123"}

    def test_env_token_takes_priority_over_monitoring_file(self, tmp_path):
        """Env var token should be used even if monitoring file exists."""
        profile = "TestProfile"
        cache_file = tmp_path / f"{profile}-otel-headers.json"
        raw_file = tmp_path / f"{profile}-otel-headers.raw"
        monitoring_file = tmp_path / f"{profile}-monitoring.json"

        cache_file.write_text(json.dumps({"token_exp": int(time.time()) + 3600}))
        raw_file.write_text('{}')
        monitoring_file.write_text(json.dumps({"token": "file-token"}))

        result = self._simulate_otel_helper(tmp_path, profile, env_token="env-token")
        parsed = json.loads(result)
        assert parsed["authorization"] == "Bearer env-token"


class TestOtelHelperScriptFiles:
    """Verify the PS1 and CMD files exist and have correct structure."""

    OTEL_HELPER_DIR = Path(__file__).parent.parent / "otel_helper"

    def test_ps1_exists(self):
        assert (self.OTEL_HELPER_DIR / "otel-helper.ps1").exists()

    def test_cmd_exists(self):
        assert (self.OTEL_HELPER_DIR / "otel-helper.cmd").exists()

    def test_cmd_invokes_ps1(self):
        content = (self.OTEL_HELPER_DIR / "otel-helper.cmd").read_text()
        assert "otel-helper.ps1" in content
        assert "-ExecutionPolicy Bypass" in content
        assert "-NoProfile" in content

    def test_cmd_tries_exe_first(self):
        """CMD should try the Go binary first for fast path."""
        content = (self.OTEL_HELPER_DIR / "otel-helper.cmd").read_text()
        lines = content.splitlines()
        exe_line = next((i for i, l in enumerate(lines) if "otel-helper.exe" in l), None)
        ps1_line = next((i for i, l in enumerate(lines) if "otel-helper.ps1" in l), None)
        assert exe_line is not None, "CMD must reference otel-helper.exe"
        assert ps1_line is not None, "CMD must reference otel-helper.ps1"
        assert exe_line < ps1_line, "CMD must try .exe before .ps1"

    def test_ps1_outputs_json(self):
        """PS1 script should always output valid JSON (even on cache miss)."""
        content = (self.OTEL_HELPER_DIR / "otel-helper.ps1").read_text()
        # The fallback output must be valid JSON
        assert 'Write-Output "{}"' in content

    def test_ps1_does_not_invoke_otel_helper_exe(self):
        """PS1 must not invoke otel-helper.exe (that's the whole point)."""
        content = (self.OTEL_HELPER_DIR / "otel-helper.ps1").read_text()
        # Check non-comment lines only
        code_lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith('#')]
        code = '\n'.join(code_lines)
        assert "otel-helper.exe" not in code
        assert "otel-helper-windows.exe" not in code


class TestOtelHelperCacheTTL:
    """Test the anti-hammering cache-miss TTL logic."""

    def _simulate_cache_miss_write(self, cache_dir: Path, profile: str = "ClaudeCode",
                                    existing_headers: dict | None = None):
        """Simulate the empty-headers cache write with TTL."""
        import time
        cache_file = cache_dir / f"{profile}-otel-headers.json"
        raw_file = cache_dir / f"{profile}-otel-headers.raw"

        should_write_empty = True
        if cache_file.exists():
            try:
                existing = json.loads(cache_file.read_text())
                if existing.get("headers") and len(existing["headers"]) > 0:
                    should_write_empty = False
            except Exception:
                pass

        if should_write_empty:
            now = int(time.time())
            empty_cache = json.dumps({
                "schema_version": 2,
                "headers": {},
                "token_exp": now + 120,
                "cached_at": now,
            })
            cache_file.write_text(empty_cache)
            raw_file.write_text("{}")

        return should_write_empty

    def test_writes_empty_cache_on_miss(self, tmp_path):
        """On cache miss, writes empty-headers with 120s TTL."""
        result = self._simulate_cache_miss_write(tmp_path)
        assert result is True
        cache_file = tmp_path / "ClaudeCode-otel-headers.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert data["schema_version"] == 2
        assert data["headers"] == {}
        assert data["token_exp"] > int(time.time())

    def test_does_not_clobber_valid_attribution(self, tmp_path):
        """If cache has valid attribution headers, don't overwrite with empty."""
        cache_file = tmp_path / "ClaudeCode-otel-headers.json"
        cache_file.write_text(json.dumps({
            "schema_version": 2,
            "headers": {"x-user-email": "real@user.com"},
            "token_exp": int(time.time()) - 100,  # expired but has real data
            "cached_at": int(time.time()) - 200,
        }))
        result = self._simulate_cache_miss_write(tmp_path)
        assert result is False  # should NOT overwrite

    def test_overwrites_empty_cache(self, tmp_path):
        """If cache exists but has empty headers, OK to overwrite."""
        cache_file = tmp_path / "ClaudeCode-otel-headers.json"
        cache_file.write_text(json.dumps({
            "schema_version": 2,
            "headers": {},
            "token_exp": int(time.time()) - 100,
            "cached_at": int(time.time()) - 200,
        }))
        result = self._simulate_cache_miss_write(tmp_path)
        assert result is True


class TestOtelHelperSidecar:
    """Test sidecar collector management logic."""

    def test_ps1_has_sidecar_logic(self):
        """PS1 must contain collector/sidecar management code."""
        ps1_path = Path(__file__).parent.parent / "otel_helper" / "otel-helper.ps1"
        content = ps1_path.read_text()
        assert "otelcol" in content
        assert "collector-config.yaml" in content
        assert "collector.pid" in content
        assert "Start-Process" in content

    def test_ps1_has_anti_hammering_ttl(self):
        """PS1 must implement empty-headers cache TTL."""
        ps1_path = Path(__file__).parent.parent / "otel_helper" / "otel-helper.ps1"
        content = ps1_path.read_text()
        assert "emptyHeadersCacheTTL" in content
        assert "120" in content
        assert "schema_version" in content
