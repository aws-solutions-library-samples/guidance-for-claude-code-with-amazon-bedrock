"""
E2E Tests — Quota Enforcement

Verifies quota checking, blocking, alerting, and fine-grained
policy enforcement via DynamoDB.
"""

import uuid

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


@pytest.fixture
def test_user():
    """Generate a unique test user for quota isolation."""
    return f"e2e-test-{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture
def quota_table(stack_outputs):
    """Get DynamoDB quota table name from stack outputs."""
    table = stack_outputs.get("QuotaTableName")
    if not table:
        pytest.skip("QuotaTableName not in stack outputs")
    return table


class TestQuotaEnforcement:
    """Quota enforcement tests — only for profiles with quota.enabled."""

    def test_under_quota_allows(
        self, run_credential_process, seed_quota_usage, quota_table, test_user
    ):
        """Fresh user with low usage is allowed (exit 0)."""
        # Seed minimal usage
        seed_quota_usage(quota_table, test_user, tokens=10)

        result = run_credential_process(
            context="initial",
            extra_env={"CCWB_USER_EMAIL": test_user},
        )

        assert result.returncode == 0, (
            f"Under-quota user blocked (exit {result.returncode}): {result.stderr}"
        )

    def test_over_quota_blocks(
        self,
        run_credential_process,
        seed_quota_usage,
        quota_table,
        test_user,
        e2e_profile,
    ):
        """Over-limit user is blocked with non-zero exit (enforcement=block only)."""
        if e2e_profile["quota"].get("enforcement") != "block":
            pytest.skip("Only applicable for enforcement=block")

        # Seed way over limit
        seed_quota_usage(quota_table, test_user, tokens=999_999_999)

        result = run_credential_process(
            context="initial",
            extra_env={"CCWB_USER_EMAIL": test_user},
        )

        assert result.returncode != 0, (
            "Over-quota user should be blocked (non-zero exit)"
        )
        assert "quota" in result.stderr.lower() or "limit" in result.stderr.lower(), (
            f"Expected quota-related error message, got: {result.stderr}"
        )

    def test_over_quota_alerts(
        self,
        run_credential_process,
        seed_quota_usage,
        quota_table,
        test_user,
        e2e_profile,
    ):
        """Over-limit user gets warning on stderr but still exits 0 (enforcement=alert)."""
        if e2e_profile["quota"].get("enforcement") != "alert":
            pytest.skip("Only applicable for enforcement=alert")

        # Seed over limit
        seed_quota_usage(quota_table, test_user, tokens=999_999_999)

        result = run_credential_process(
            context="initial",
            extra_env={"CCWB_USER_EMAIL": test_user},
        )

        assert result.returncode == 0, (
            f"Alert-only quota should not block (exit {result.returncode})"
        )

        # Should have warning on stderr
        stderr_lower = result.stderr.lower()
        assert (
            "quota" in stderr_lower
            or "warning" in stderr_lower
            or "limit" in stderr_lower
        ), f"Expected quota warning on stderr, got: {result.stderr}"

    def test_quota_recheck_refreshes_token(
        self, run_credential_process, seed_quota_usage, quota_table, test_user
    ):
        """Quota recheck with expired token triggers token refresh."""
        seed_quota_usage(quota_table, test_user, tokens=10)

        result = run_credential_process(
            context="mid-session-refresh",
            extra_env={
                "CCWB_USER_EMAIL": test_user,
                "CCWB_TOKEN_EXPIRY_OVERRIDE": "2020-01-01T00:00:00Z",
            },
        )

        # Should still succeed (refresh + quota check)
        assert result.returncode == 0, (
            f"Quota recheck with refresh failed: {result.stderr}"
        )

    def test_fine_grained_user_policy_overrides_default(
        self,
        run_credential_process,
        seed_quota_usage,
        set_user_quota_policy,
        quota_table,
        test_user,
        e2e_profile,
    ):
        """Per-user DynamoDB policy overrides default limit (fine_grained only)."""
        if not e2e_profile["quota"].get("fine_grained"):
            pytest.skip("Only applicable for fine_grained=true profiles")

        # Seed usage that exceeds default but is under per-user limit
        seed_quota_usage(quota_table, test_user, tokens=50_000)

        # Set generous per-user policy
        set_user_quota_policy(quota_table, test_user, limit=100_000)

        result = run_credential_process(
            context="initial",
            extra_env={"CCWB_USER_EMAIL": test_user},
        )

        assert result.returncode == 0, (
            f"User with generous per-user policy should pass: {result.stderr}"
        )

    def test_fine_grained_group_policy(
        self,
        run_credential_process,
        seed_quota_usage,
        set_group_quota_policy,
        quota_table,
        test_user,
        e2e_profile,
    ):
        """Group-level DynamoDB policy applies to group members (fine_grained only)."""
        if not e2e_profile["quota"].get("fine_grained"):
            pytest.skip("Only applicable for fine_grained=true profiles")

        test_group = f"e2e-group-{uuid.uuid4().hex[:8]}"

        # Seed usage under group limit
        seed_quota_usage(quota_table, test_user, tokens=5_000)

        # Set group policy
        set_group_quota_policy(quota_table, test_group, limit=10_000)

        result = run_credential_process(
            context="initial",
            extra_env={
                "CCWB_USER_EMAIL": test_user,
                "CCWB_USER_GROUP": test_group,
            },
        )

        assert result.returncode == 0, (
            f"User under group quota should pass: {result.stderr}"
        )

    def test_quota_fail_open_on_api_error(self, run_credential_process, test_user):
        """When quota API is unreachable, credential-process still allows (fail-open)."""
        result = run_credential_process(
            context="initial",
            extra_env={
                "CCWB_USER_EMAIL": test_user,
                # Point to unreachable endpoint to simulate API failure
                "CCWB_QUOTA_ENDPOINT_OVERRIDE": "http://192.0.2.1:1/quota",
                "CCWB_QUOTA_TIMEOUT_MS": "2000",
            },
        )

        assert result.returncode == 0, (
            f"Quota should fail-open when API unreachable (exit {result.returncode}): {result.stderr}"
        )
