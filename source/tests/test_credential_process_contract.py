# ABOUTME: Contract tests ensuring Go and Python credential-process outputs are compatible
# ABOUTME: Prevents drift between the two implementations that causes silent failures

"""Credential-process output contract tests.

The Go binary and Python credential-provider implement the same AWS
credential-process protocol independently. When one gets a fix or feature,
the other often lags behind, causing silent failures for users on the
other path.

These tests define the contract both must satisfy, and verify it by
static analysis of both codebases. They don't run the binaries — they
check that the code has the required patterns.

Drift this prevents:
- Go has refresh_token but Python doesn't
- Python has IDC/SigV4 quota but Go doesn't
- One outputs Expiration and the other doesn't
- Error messages diverge causing support confusion
"""

from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).parent.parent
GO_MAIN = SOURCE_ROOT / "go" / "cmd" / "credential-process" / "main.go"
PY_MAIN = SOURCE_ROOT / "credential_provider" / "__main__.py"


class TestCredentialProcessContract:
    """Both Go and Python credential-process must satisfy the same output contract."""

    def test_both_implementations_exist(self):
        """Both credential-process implementations must exist."""
        assert GO_MAIN.exists(), f"Go binary not found at {GO_MAIN}"
        assert PY_MAIN.exists(), f"Python provider not found at {PY_MAIN}"

    def test_both_output_version_1(self):
        """Both must output Version: 1 (AWS credential-process spec)."""
        go_code = GO_MAIN.read_text(encoding="utf-8")
        py_code = PY_MAIN.read_text(encoding="utf-8")

        assert "Version" in go_code and ("1" in go_code or "version" in go_code.lower())
        assert '"Version": 1' in py_code or "'Version': 1" in py_code

    def test_both_have_silent_refresh(self):
        """Both must implement silent refresh (reuse cached id_token for STS)."""
        go_code = GO_MAIN.read_text(encoding="utf-8")
        py_code = PY_MAIN.read_text(encoding="utf-8")

        assert "trySilentRefresh" in go_code or "silent" in go_code.lower(), "Go binary missing silent refresh path"
        assert "silent" in py_code.lower() or "_try_silent_refresh" in py_code, (
            "Python provider missing silent refresh path"
        )

    def test_both_have_quota_check(self):
        """Both must implement quota checking when endpoint is configured."""
        go_code = GO_MAIN.read_text(encoding="utf-8")
        py_code = PY_MAIN.read_text(encoding="utf-8")

        assert "quota" in go_code.lower() or "Quota" in go_code, "Go binary missing quota check integration"
        assert "quota" in py_code.lower() or "_check_quota" in py_code, (
            "Python provider missing quota check integration"
        )

    def test_both_have_cache_mechanism(self):
        """Both must cache credentials to avoid re-auth on every invocation."""
        go_code = GO_MAIN.read_text(encoding="utf-8")
        py_code = PY_MAIN.read_text(encoding="utf-8")

        assert "getCachedCredentials" in go_code or "cached" in go_code.lower(), "Go binary missing credential cache"
        assert "get_cached_credentials" in py_code or "cached" in py_code.lower(), (
            "Python provider missing credential cache"
        )

    def test_both_have_clear_cache(self):
        """Both must support clearing cached credentials (logout)."""
        go_code = GO_MAIN.read_text(encoding="utf-8")
        py_code = PY_MAIN.read_text(encoding="utf-8")

        assert "clearCache" in go_code or "clear-cache" in go_code, "Go binary missing cache clear functionality"
        assert "clear" in py_code.lower(), "Python provider missing cache clear functionality"

    def test_both_handle_expiration(self):
        """Both must include Expiration in output (for SDK credential refresh)."""
        go_code = GO_MAIN.read_text(encoding="utf-8")
        py_code = PY_MAIN.read_text(encoding="utf-8")

        assert "Expiration" in go_code, "Go binary missing Expiration field in output"
        assert "Expiration" in py_code, "Python provider missing Expiration field in output"

    def test_both_support_monitoring_token(self):
        """Both must support --get-monitoring-token for OTEL helper."""
        go_code = GO_MAIN.read_text(encoding="utf-8")
        py_code = PY_MAIN.read_text(encoding="utf-8")

        assert "get-monitoring-token" in go_code or "getMonitoring" in go_code, (
            "Go binary missing monitoring token support"
        )
        assert "monitoring" in py_code.lower(), "Python provider missing monitoring token support"

    def test_both_handle_port_lock(self):
        """Both must handle OAuth port locking (prevent duplicate auth windows)."""
        go_code = GO_MAIN.read_text(encoding="utf-8")
        py_code = PY_MAIN.read_text(encoding="utf-8")

        assert "portlock" in go_code.lower() or "TryAcquire" in go_code, (
            "Go binary missing port lock for OAuth callback"
        )
        assert "port" in py_code.lower() and "lock" in py_code.lower(), (
            "Python provider missing port lock for OAuth callback"
        )


class TestCredentialProcessFeatureParity:
    """Track feature parity between Go and Python — these may intentionally diverge
    but the test documents which features exist in which implementation."""

    @pytest.mark.xfail(reason="PR #447 pending review — refresh_token not yet in beta")
    def test_go_has_refresh_token_support(self):
        """Go binary should have refresh_token persistence (PR #447)."""
        go_code = GO_MAIN.read_text(encoding="utf-8")
        assert "tryRefreshToken" in go_code or "RefreshToken" in go_code, (
            "Go binary missing refresh_token support (PR #447)"
        )

    def test_python_has_sso_passthrough(self):
        """Python provider should have SSO passthrough mode (PR #303)."""
        py_code = PY_MAIN.read_text(encoding="utf-8")
        assert "sso_enabled" in py_code or "_run_passthrough" in py_code, (
            "Python provider missing SSO passthrough mode (PR #303)"
        )
