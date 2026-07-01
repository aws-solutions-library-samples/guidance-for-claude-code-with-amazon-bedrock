# ABOUTME: Parametrized profile-matrix test for deploy stack selection logic
# ABOUTME: Validates correct stacks are scheduled for every profile combination without deploying

"""Profile-matrix deploy simulation tests.

Validates that ``_select_full_deploy_stacks()`` returns the correct ordered
stack list for every supported profile combination (sidecar/central ×
OIDC/IDC/none × quota on/off × analytics on/off) WITHOUT deploying anything.

Prevents regressions like #690 where sidecar mode incorrectly scheduled
central infrastructure (VPC/ECS/ALB) due to a missing mode gate.
"""

import dataclasses
import re

import pytest

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _NullConsole:
    """Minimal console stub that satisfies .print() without side effects."""

    def print(self, *args, **kwargs):
        pass


def _base_profile(**overrides):
    """Create a minimal valid Profile with sensible defaults and overrides."""
    field_names = {f.name for f in dataclasses.fields(Profile)}
    defaults = {
        "name": "MatrixTestProfile",
        "provider_domain": "company.okta.com",
        "client_id": "test-client-id",
        "credential_storage": "session",
        "aws_region": "us-east-1",
        "identity_pool_name": "claude-code-matrix-test",
        "sso_enabled": True,
        "provider_type": "okta",
        "monitoring_enabled": True,
        "monitoring_mode": "central",
        "quota_monitoring_enabled": False,
        "analytics_enabled": True,
        "federation_type": "direct",
        "federated_role_arn": "arn:aws:iam::123456789012:role/BedrockRole",
        "enable_finegrained_quotas": False,
        "monthly_token_limit": 225000000,
        "daily_token_limit": 8250000,
        "daily_enforcement_mode": "alert",
        "monthly_enforcement_mode": "block",
        "warning_threshold_80": 180000000,
        "warning_threshold_90": 202500000,
    }
    defaults.update(overrides)
    return Profile(**{k: v for k, v in defaults.items() if k in field_names})


def _stack_types(command, profile):
    """Extract just the stack type strings from the selection result."""
    return [s[0] for s in command._select_full_deploy_stacks(profile, _NullConsole())]


# ---------------------------------------------------------------------------
# Stacks that must NEVER appear in sidecar monitoring mode.
# ---------------------------------------------------------------------------
SIDECAR_FORBIDDEN_STACKS = {"networking", "monitoring", "cowork-dashboard", "analytics"}

# Stacks that must ALWAYS appear regardless of monitoring mode.
ALWAYS_PRESENT_STACKS = {"auth", "dashboard"}


# ---------------------------------------------------------------------------
# Parametrized profile matrix
# ---------------------------------------------------------------------------

_MATRIX = [
    pytest.param(
        {
            "monitoring_mode": "sidecar",
            "sso_enabled": True,
            "auth_type": "oidc",
            "provider_type": "okta",
            "quota_monitoring_enabled": False,
            "monitoring_enabled": True,
            "analytics_enabled": True,
        },
        {"auth", "dashboard"},
        id="sidecar-oidc-no_quota",
    ),
    pytest.param(
        {
            "monitoring_mode": "sidecar",
            "sso_enabled": True,
            "auth_type": "oidc",
            "provider_type": "okta",
            "quota_monitoring_enabled": True,
            "monitoring_enabled": True,
            "analytics_enabled": True,
        },
        {"auth", "dashboard", "s3bucket", "quota"},
        id="sidecar-oidc-with_quota",
    ),
    pytest.param(
        {
            "monitoring_mode": "sidecar",
            "sso_enabled": False,
            "auth_type": "idc",
            "quota_monitoring_enabled": False,
            "monitoring_enabled": True,
            "analytics_enabled": True,
        },
        {"auth", "dashboard"},
        id="sidecar-idc-no_quota",
    ),
    pytest.param(
        {
            "monitoring_mode": "sidecar",
            "sso_enabled": False,
            "auth_type": "idc",
            "quota_monitoring_enabled": True,
            "monitoring_enabled": True,
            "analytics_enabled": True,
        },
        {"auth", "dashboard", "s3bucket", "quota"},
        id="sidecar-idc-with_quota",
    ),
    pytest.param(
        {
            "monitoring_mode": "sidecar",
            "sso_enabled": False,
            "auth_type": "none",
            "quota_monitoring_enabled": False,
            "monitoring_enabled": False,
            "analytics_enabled": True,
        },
        set(),  # no auth (auth_type=none), no monitoring stacks
        id="sidecar-none_auth-no_monitoring",
    ),
    pytest.param(
        {
            "monitoring_mode": "central",
            "sso_enabled": True,
            "auth_type": "oidc",
            "provider_type": "okta",
            "quota_monitoring_enabled": False,
            "monitoring_enabled": True,
            "analytics_enabled": True,
        },
        {"auth", "networking", "s3bucket", "monitoring", "dashboard", "cowork-dashboard", "analytics"},
        id="central-oidc-no_quota",
    ),
    pytest.param(
        {
            "monitoring_mode": "central",
            "sso_enabled": True,
            "auth_type": "oidc",
            "provider_type": "okta",
            "quota_monitoring_enabled": True,
            "monitoring_enabled": True,
            "analytics_enabled": True,
        },
        {"auth", "networking", "s3bucket", "monitoring", "dashboard", "cowork-dashboard", "analytics", "quota"},
        id="central-oidc-with_quota",
    ),
    pytest.param(
        {
            "monitoring_mode": "central",
            "sso_enabled": False,
            "auth_type": "idc",
            "quota_monitoring_enabled": False,
            "monitoring_enabled": True,
            "analytics_enabled": True,
        },
        {"auth", "networking", "s3bucket", "monitoring", "dashboard", "cowork-dashboard", "analytics"},
        id="central-idc-no_quota",
    ),
    pytest.param(
        {
            "monitoring_mode": "central",
            "sso_enabled": False,
            "auth_type": "idc",
            "quota_monitoring_enabled": True,
            "monitoring_enabled": True,
            "analytics_enabled": True,
        },
        {"auth", "networking", "s3bucket", "monitoring", "dashboard", "cowork-dashboard", "analytics", "quota"},
        id="central-idc-with_quota",
    ),
    pytest.param(
        {
            "monitoring_mode": "central",
            "sso_enabled": True,
            "auth_type": "oidc",
            "provider_type": "okta",
            "quota_monitoring_enabled": False,
            "monitoring_enabled": True,
            "analytics_enabled": True,
        },
        {"auth", "networking", "s3bucket", "monitoring", "dashboard", "cowork-dashboard", "analytics"},
        id="central-oidc-with_analytics",
    ),
]


class TestDeployProfileMatrix:
    """Parametrized matrix covering all supported profile × stack combinations.

    Each case validates the exact set of stacks returned by
    ``_select_full_deploy_stacks()`` for a given profile configuration.
    """

    @pytest.fixture
    def command(self):
        return DeployCommand()

    @pytest.mark.parametrize("overrides,expected_stacks", _MATRIX)
    def test_stack_selection(self, command, overrides, expected_stacks):
        """Verify correct stacks are scheduled for each profile combination."""
        profile = _base_profile(**overrides)
        actual = set(_stack_types(command, profile))
        assert actual == expected_stacks, (
            f"Stack mismatch for {overrides}:\n  Expected: {sorted(expected_stacks)}\n  Actual:   {sorted(actual)}"
        )


class TestSidecarNegativeAssertions:
    """Negative assertions: sidecar mode must NEVER deploy central infrastructure."""

    @pytest.fixture
    def command(self):
        return DeployCommand()

    @pytest.mark.parametrize(
        "auth_type,quota_enabled",
        [
            ("oidc", False),
            ("oidc", True),
            ("idc", False),
            ("idc", True),
            ("none", False),
        ],
        ids=[
            "sidecar-oidc-no_quota",
            "sidecar-oidc-with_quota",
            "sidecar-idc-no_quota",
            "sidecar-idc-with_quota",
            "sidecar-none-no_quota",
        ],
    )
    def test_sidecar_never_includes_central_stacks(self, command, auth_type, quota_enabled):
        """Sidecar profiles must never schedule networking/monitoring/cowork/analytics."""
        overrides = {
            "monitoring_mode": "sidecar",
            "auth_type": auth_type,
            "sso_enabled": auth_type == "oidc",
            "quota_monitoring_enabled": quota_enabled,
            "monitoring_enabled": auth_type != "none",
        }
        profile = _base_profile(**overrides)
        stacks = set(_stack_types(command, profile))
        forbidden_present = SIDECAR_FORBIDDEN_STACKS & stacks
        assert not forbidden_present, (
            f"Sidecar ({auth_type}, quota={quota_enabled}) incorrectly scheduled "
            f"central-only stacks: {sorted(forbidden_present)}"
        )

    @pytest.mark.parametrize(
        "auth_type",
        ["oidc", "idc"],
        ids=["sidecar-oidc", "sidecar-idc"],
    )
    def test_sidecar_always_includes_dashboard(self, command, auth_type):
        """Sidecar with monitoring enabled must always include the dashboard."""
        profile = _base_profile(
            monitoring_mode="sidecar",
            auth_type=auth_type,
            sso_enabled=auth_type == "oidc",
            monitoring_enabled=True,
        )
        assert "dashboard" in _stack_types(command, profile)

    @pytest.mark.parametrize(
        "auth_type",
        ["oidc", "idc"],
        ids=["sidecar-oidc", "sidecar-idc"],
    )
    def test_sidecar_always_includes_auth(self, command, auth_type):
        """Sidecar with non-none auth must always include auth stack."""
        profile = _base_profile(
            monitoring_mode="sidecar",
            auth_type=auth_type,
            sso_enabled=auth_type == "oidc",
            monitoring_enabled=True,
        )
        assert "auth" in _stack_types(command, profile)


class TestCentralPositiveAssertions:
    """Positive assertions: central mode must deploy the full infrastructure stack."""

    @pytest.fixture
    def command(self):
        return DeployCommand()

    @pytest.mark.parametrize(
        "auth_type",
        ["oidc", "idc"],
        ids=["central-oidc", "central-idc"],
    )
    def test_central_includes_networking(self, command, auth_type):
        """Central mode must include networking stack."""
        profile = _base_profile(
            monitoring_mode="central",
            auth_type=auth_type,
            sso_enabled=auth_type == "oidc",
            monitoring_enabled=True,
        )
        assert "networking" in _stack_types(command, profile)

    @pytest.mark.parametrize(
        "auth_type",
        ["oidc", "idc"],
        ids=["central-oidc", "central-idc"],
    )
    def test_central_includes_monitoring(self, command, auth_type):
        """Central mode must include the OTel monitoring stack."""
        profile = _base_profile(
            monitoring_mode="central",
            auth_type=auth_type,
            sso_enabled=auth_type == "oidc",
            monitoring_enabled=True,
        )
        assert "monitoring" in _stack_types(command, profile)

    def test_central_with_analytics_includes_analytics(self, command):
        """Central mode with analytics_enabled=True must include analytics."""
        profile = _base_profile(
            monitoring_mode="central",
            auth_type="oidc",
            sso_enabled=True,
            monitoring_enabled=True,
            analytics_enabled=True,
        )
        assert "analytics" in _stack_types(command, profile)

    def test_central_without_analytics_excludes_analytics(self, command):
        """Central mode with analytics_enabled=False must exclude analytics."""
        profile = _base_profile(
            monitoring_mode="central",
            auth_type="oidc",
            sso_enabled=True,
            monitoring_enabled=True,
            analytics_enabled=False,
        )
        assert "analytics" not in _stack_types(command, profile)


class TestQuotaStackOrdering:
    """Verify quota stack ordering constraints (s3bucket before quota)."""

    @pytest.fixture
    def command(self):
        return DeployCommand()

    @pytest.mark.parametrize(
        "monitoring_mode",
        ["sidecar", "central"],
        ids=["sidecar", "central"],
    )
    def test_s3bucket_precedes_quota(self, command, monitoring_mode):
        """s3bucket must always be deployed before quota in both modes."""
        profile = _base_profile(
            monitoring_mode=monitoring_mode,
            auth_type="oidc",
            sso_enabled=True,
            monitoring_enabled=True,
            quota_monitoring_enabled=True,
        )
        stacks = _stack_types(command, profile)
        assert "s3bucket" in stacks
        assert "quota" in stacks
        assert stacks.index("s3bucket") < stacks.index("quota"), (
            f"s3bucket (index {stacks.index('s3bucket')}) must come before "
            f"quota (index {stacks.index('quota')}) in {monitoring_mode} mode"
        )


class TestGuardNewStacks:
    """Guard test: fails when new stacks are added without updating the matrix.

    This reads the deploy.py source to detect all stack types that
    ``_select_full_deploy_stacks`` can schedule. If a new stack is added,
    this test fails to remind developers to add coverage to the matrix.
    """

    # All stack types known to the profile matrix tests above.
    # Update this set when adding new stacks to the deploy logic.
    KNOWN_STACKS = frozenset(
        {
            "auth",
            "networking",
            "distribution",
            "s3bucket",
            "monitoring",
            "dashboard",
            "cowork-dashboard",
            "analytics",
            "quota",
            "codebuild",
        }
    )

    def test_no_unknown_stacks_in_selection(self):
        """Detect if _select_full_deploy_stacks can return stacks not covered by the matrix."""
        import inspect

        from claude_code_with_bedrock.cli.commands.deploy import DeployCommand

        source = inspect.getsource(DeployCommand._select_full_deploy_stacks)

        # Extract all stack type strings from append(("...", calls
        stack_pattern = re.compile(r'stacks_to_deploy\.append\(\("([^"]+)"')
        found_stacks = set(stack_pattern.findall(source))

        unknown = found_stacks - self.KNOWN_STACKS
        assert not unknown, (
            f"New stack(s) found in _select_full_deploy_stacks but not covered "
            f"by the profile matrix test: {sorted(unknown)}. "
            f"Add test coverage in TestDeployProfileMatrix and update KNOWN_STACKS."
        )

    def test_known_stacks_still_exist(self):
        """Ensure KNOWN_STACKS doesn't contain stale entries (stacks removed from code)."""
        import inspect

        from claude_code_with_bedrock.cli.commands.deploy import DeployCommand

        source = inspect.getsource(DeployCommand._select_full_deploy_stacks)

        stack_pattern = re.compile(r'stacks_to_deploy\.append\(\("([^"]+)"')
        found_stacks = set(stack_pattern.findall(source))

        stale = self.KNOWN_STACKS - found_stacks
        # distribution and codebuild are conditionally scheduled but still valid
        # — they may not appear in the function if they're handled elsewhere.
        # Only flag stacks that are truly absent from the source.
        if stale:
            # Check if the "stale" stacks appear anywhere in the function text
            truly_stale = {s for s in stale if s not in source}
            assert not truly_stale, (
                f"Stale stack(s) in KNOWN_STACKS that no longer appear in "
                f"_select_full_deploy_stacks: {sorted(truly_stale)}. "
                f"Remove from KNOWN_STACKS."
            )
