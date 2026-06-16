# ABOUTME: Tests for destroy command stack coverage and skip logic
# ABOUTME: Ensures destroy tears down every stack that deploy can create

"""Tests that `ccwb destroy` covers all deployable stacks.

Regression coverage for the gap where `distribution`, `codebuild`, and
`cowork-dashboard` stacks were deployed but never destroyed, leaving
orphaned S3/IAM, CodeBuild projects, and dashboards behind.
"""

import ast
from pathlib import Path
from unittest.mock import Mock, patch

from cleo.testers.command_tester import CommandTester

from claude_code_with_bedrock.cli.commands.destroy import DESTROYABLE_STACKS, DestroyCommand

DEPLOY_SOURCE = Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands" / "deploy.py"


def _deployable_stack_types() -> set[str]:
    """Extract every stack type deploy.py can append to its deploy list.

    Uses an AST walk (not a line regex) so the detection is independent of source
    formatting: a `stacks_to_deploy.append(("name", ...))` is found whether it is on
    one line or wrapped across several. The previous single-line regex silently
    missed multi-line `.append((` forms — which already caused a false phantom once
    (see persona-based-access decisions.md). We match any call of the form
    `<x>.append((<str-literal>, ...))` where the receiver attribute is `append`, the
    sole arg is a tuple, and its first element is a string constant — then collect that
    string. This covers `stacks_to_deploy.append(...)` regardless of how the receiver
    is named/spelled, and ignores non-tuple appends (e.g. list.append(scalar)).
    """
    tree = ast.parse(DEPLOY_SOURCE.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "append"):
            continue
        # Only consider appends onto the deploy list, to avoid sweeping up unrelated
        # .append() calls elsewhere in the file.
        if not (isinstance(func.value, ast.Name) and func.value.id == "stacks_to_deploy"):
            continue
        if len(node.args) != 1 or not isinstance(node.args[0], ast.Tuple):
            continue
        elts = node.args[0].elts
        if elts and isinstance(elts[0], ast.Constant) and isinstance(elts[0].value, str):
            found.add(elts[0].value)
    return found


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


class TestPersonaInferenceProfileTeardown:
    """FR-9.5 regression: ccwb destroy must remove EVERY per-tier Application
    Inference Profile a persona could have been issued, plus the legacy name —
    driving the REAL _delete_persona_inference_profiles (not a patched no-op).

    The key invariant (M3): teardown iterates ALL tiers, not just the persona's
    *currently* entitled tiers. If an operator narrowed a persona's models after
    deploy (e.g. sales loses opus), the opus AIP still exists and must be swept or
    it orphans as a tagged, billable resource. A naive `entitled_tiers(persona)`
    loop would skip it.
    """

    def _run_real_teardown(self, persona):
        """Call the real _delete_persona_inference_profiles with a recording
        boto3 client; return the set of inferenceProfileIdentifiers it deleted."""
        deleted = []
        client = Mock()
        client.delete_inference_profile.side_effect = (
            lambda inferenceProfileIdentifier: deleted.append(inferenceProfileIdentifier)
        )
        profile = _persona_profile([persona])
        console = Mock()
        with patch("boto3.client", return_value=client):
            DestroyCommand()._delete_persona_inference_profiles(profile, console)
        return set(deleted)

    def test_sweeps_all_tiers_even_when_entitlement_shrank(self):
        # Sales is currently haiku-only (sonnet+opus denied), so entitled_tiers == {haiku}.
        # But the sonnet/opus AIPs may exist from a prior broader deploy — destroy must
        # still attempt to delete them. Assert ALL three tier names + legacy are swept.
        sales = {
            "name": "sales",
            "group": "sales-team",
            "allowed_models": ["anthropic.*haiku*"],
            "denied_models": ["anthropic.*sonnet*", "anthropic.*opus*"],
        }
        deleted = self._run_real_teardown(sales)
        assert deleted == {
            "test-pool-sales-haiku",
            "test-pool-sales-sonnet",
            "test-pool-sales-opus",
            "test-pool-sales",  # legacy pre-FR-5.1 single-name AIP
        }, f"teardown must sweep all tiers + legacy regardless of current entitlement; got {deleted}"

    def test_best_effort_on_delete_error(self):
        """A delete failure (already-gone / in-use) must not abort the sweep —
        every candidate is still attempted."""
        attempted = []

        def _boom(inferenceProfileIdentifier):
            attempted.append(inferenceProfileIdentifier)
            raise RuntimeError("ResourceNotFound")

        client = Mock()
        client.delete_inference_profile.side_effect = _boom
        profile = _persona_profile([{"name": "eng", "group": "eng-team", "allowed_models": ["anthropic.*"]}])
        with patch("boto3.client", return_value=client):
            # Must not raise.
            DestroyCommand()._delete_persona_inference_profiles(profile, Mock())
        # All four candidates (3 tiers + legacy) were attempted despite each raising.
        assert len(attempted) == 4

    def test_no_personas_is_a_clean_noop(self):
        client = Mock()
        with patch("boto3.client", return_value=client):
            DestroyCommand()._delete_persona_inference_profiles(_persona_profile([]), Mock())
        client.delete_inference_profile.assert_not_called()


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
