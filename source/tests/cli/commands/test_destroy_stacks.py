# ABOUTME: Tests for destroy command stack coverage and skip logic
# ABOUTME: Ensures destroy tears down every stack that deploy can create

"""Tests that `ccwb destroy` covers all deployable stacks.

Regression coverage for the gap where `distribution`, `codebuild`, and
`cowork-dashboard` stacks were deployed but never destroyed, leaving
orphaned S3/IAM, CodeBuild projects, and dashboards behind.
"""

import re
from pathlib import Path
from unittest.mock import Mock, patch

from cleo.testers.command_tester import CommandTester

from claude_code_with_bedrock.cli.commands.destroy import DESTROYABLE_STACKS, DestroyCommand

DEPLOY_SOURCE = Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands" / "deploy.py"


def _deployable_stack_types() -> set[str]:
    """Extract every stack type deploy.py can append to its deploy list."""
    source = DEPLOY_SOURCE.read_text(encoding="utf-8")
    return set(re.findall(r'stacks_to_deploy\.append\(\(\s*"([a-z0-9-]+)"', source))


class TestDestroyStackCoverage:
    """Every stack deploy can create must also be destroyable."""

    def test_destroy_covers_every_deployable_stack(self):
        deployable = _deployable_stack_types()
        missing = deployable - set(DESTROYABLE_STACKS)
        assert not missing, f"destroy is missing deployable stacks: {sorted(missing)}"

    def test_no_phantom_destroyable_stacks(self):
        # Destroy should not reference stacks deploy never creates.
        deployable = _deployable_stack_types()
        phantom = set(DESTROYABLE_STACKS) - deployable
        assert not phantom, f"destroy lists non-deployable stacks: {sorted(phantom)}"

    def test_previously_missing_stacks_present(self):
        for stack in ("distribution", "codebuild", "cowork-dashboard"):
            assert stack in DESTROYABLE_STACKS, f"{stack} must be destroyable"

    def test_no_duplicate_stacks(self):
        assert len(DESTROYABLE_STACKS) == len(set(DESTROYABLE_STACKS))


class TestDestroyReverseDependencyOrder:
    """Destroy runs in reverse dependency order relative to deploy."""

    def test_distribution_destroyed_before_networking(self):
        # distribution reads networking outputs, so it must be torn down first.
        assert DESTROYABLE_STACKS.index("distribution") < DESTROYABLE_STACKS.index("networking")

    def test_auth_destroyed_last(self):
        # auth is the root dependency; everything else goes first.
        assert DESTROYABLE_STACKS[-1] == "auth"

    def test_dependents_before_monitoring(self):
        # dashboard / cowork-dashboard / analytics / quota depend on monitoring.
        monitoring_idx = DESTROYABLE_STACKS.index("monitoring")
        for dependent in ("dashboard", "cowork-dashboard", "analytics", "quota"):
            assert DESTROYABLE_STACKS.index(dependent) < monitoring_idx

    def test_persona_dashboard_not_in_destroyable_stacks(self):
        # The persona-dashboard stack is deployed INLINE (not a scheduled stack
        # type), so it must NOT be a DESTROYABLE_STACKS entry — otherwise
        # test_no_phantom_destroyable_stacks fails (the regex can't see an inline
        # method call). It is torn down explicitly via _delete_persona_dashboard_stack.
        assert "persona-dashboard" not in DESTROYABLE_STACKS


def _persona_profile(personas):
    """Mock profile for behavioral destroy tests. `personas` is set explicitly
    (a bare Mock attribute is truthy, which would defeat the no-persona guard)."""
    p = Mock()
    p.identity_pool_name = "test-pool"
    p.stack_names = {}
    p.monitoring_enabled = False  # skip ECS/monitoring stacks; isolate persona teardown
    p.monitoring_mode = "central"
    p.quota_monitoring_enabled = False
    p.enable_distribution = False
    p.enable_codebuild = False
    p.aws_region = "us-east-1"
    p.personas = personas
    return p


def _run_destroy(profile):
    """Run `destroy --force` with a mocked profile; return the set of stack names
    `_delete_stack` was invoked for (with the `test-pool-` prefix stripped).

    `_delete_persona_inference_profiles` is patched to a no-op — it is a separate
    concern (boto3 AIP cleanup) with its own coverage; here we isolate the
    persona-dashboard CFN-stack teardown, which goes through `_delete_stack`.
    """
    deleted = []
    with (
        patch("claude_code_with_bedrock.cli.commands.destroy.Config") as MockConfig,
        patch.object(DestroyCommand, "_delete_stack", return_value=0) as mock_delete,
        patch.object(DestroyCommand, "_get_failed_resources", return_value=[]),
        patch.object(DestroyCommand, "_get_retained_resources", return_value=[]),
        patch.object(DestroyCommand, "_delete_persona_inference_profiles"),
        patch.object(DestroyCommand, "_show_cleanup_summary"),
    ):
        MockConfig.load.return_value.get_profile.return_value = profile
        MockConfig.load.return_value.active_profile = "test"
        mock_delete.side_effect = lambda stack_name, region, console: deleted.append(stack_name) or 0

        tester = CommandTester(DestroyCommand())
        exit_code = tester.execute("--force")

    return exit_code, {name.replace("test-pool-", "") for name in deleted}


class TestPersonaDashboardTeardown:
    """FR-9.5 regression: ccwb destroy must tear down the inline persona-dashboard
    CFN stack (review-1 W3). It is created outside DESTROYABLE_STACKS, so the
    explicit _delete_persona_dashboard_stack path must cover it."""

    def test_dashboard_stack_deleted_when_personas_configured(self):
        exit_code, deleted = _run_destroy(_persona_profile([{"name": "engineering", "group": "eng-team"}]))
        assert exit_code == 0
        assert "persona-dashboard" in deleted, (
            "ccwb destroy must delete the inline {pool}-persona-dashboard stack when personas are configured (FR-9.5)"
        )
        # The persona stack itself is still torn down by the main loop.
        assert "persona" in deleted

    def test_dashboard_stack_skipped_when_no_personas(self):
        exit_code, deleted = _run_destroy(_persona_profile([]))
        assert exit_code == 0
        assert "persona-dashboard" not in deleted, (
            "persona-dashboard teardown must be skipped cleanly when no personas exist"
        )
        # persona/budgets stacks are likewise skipped without personas.
        assert "persona" not in deleted
        assert "budgets" not in deleted
