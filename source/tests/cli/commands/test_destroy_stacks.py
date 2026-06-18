# ABOUTME: Tests for destroy command stack coverage and skip logic
# ABOUTME: Ensures destroy tears down every stack that deploy can create

"""Tests that `ccwb destroy` covers all deployable stacks.

Regression coverage for the gap where `distribution`, `codebuild`, and
`cowork-dashboard` stacks were deployed but never destroyed, leaving
orphaned S3/IAM, CodeBuild projects, and dashboards behind.
"""

import re
from pathlib import Path

from claude_code_with_bedrock.cli.commands.destroy import DESTROYABLE_STACKS

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
