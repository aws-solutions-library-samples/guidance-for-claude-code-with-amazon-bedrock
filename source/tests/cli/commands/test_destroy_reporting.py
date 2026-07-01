# ABOUTME: Regression tests for destroy summary reporting correctness
# ABOUTME: A stack that errors with no enumerable DELETE_FAILED resources must not report success

"""Regression coverage for the false "All stacks destroyed successfully!" report.

When `_delete_stack` returns non-zero (e.g. a real error, or a client-side timeout while
resources are still DELETE_IN_PROGRESS) and `_get_failed_resources` returns an empty list,
the stack must still be tracked as failed and the summary must not claim success.
"""

from unittest.mock import Mock, patch

from cleo.testers.command_tester import CommandTester
from rich.console import Console

from claude_code_with_bedrock.cli.commands.destroy import DestroyCommand


def _profile(**overrides):
    p = Mock()
    p.identity_pool_name = "test-pool"
    p.stack_names = {}
    p.monitoring_enabled = True
    p.monitoring_mode = "central"
    p.quota_monitoring_enabled = False
    p.enable_distribution = False
    p.enable_codebuild = False
    p.aws_region = "us-east-1"
    p.codebuild_region = None  # explicit: Mock would otherwise auto-create a truthy attr
    p.codebuild_prior_regions = []  # explicit: Mock would otherwise be a non-iterable truthy attr
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def test_errored_stack_with_no_failed_resources_is_tracked():
    """A non-zero delete result with empty failed-resources must reach the summary as a failure."""
    captured = {}

    def _spy_summary(self, failed_resources, retained_resources, stacks, profile, console):
        captured["stacks"] = list(stacks)

    # auth (the always-deleted stack) errors with code 2; everything else "succeeds".
    def _delete(self, stack_name, region, console):
        return 2 if stack_name.endswith("-auth") else 0

    with (
        patch("claude_code_with_bedrock.cli.commands.destroy.Config") as MockConfig,
        patch.object(DestroyCommand, "_delete_stack", _delete),
        patch.object(DestroyCommand, "_get_failed_resources", return_value=[]),
        patch.object(DestroyCommand, "_get_retained_resources", return_value=[]),
        patch.object(DestroyCommand, "_show_cleanup_summary", _spy_summary),
    ):
        MockConfig.load.return_value.get_profile.return_value = _profile()
        MockConfig.load.return_value.active_profile = "test"
        CommandTester(DestroyCommand()).execute("--force")

    assert captured["stacks"], "errored stack must be recorded in stacks_with_failures"
    assert any(s.endswith("-auth") for s in captured["stacks"])


def test_summary_does_not_claim_success_for_errored_stack():
    """_show_cleanup_summary with a failed stack but no per-resource rows must not print success."""
    console = Console(record=True, width=120)
    DestroyCommand()._show_cleanup_summary(
        failed_resources=[],
        retained_resources=[],
        stacks=["test-pool-monitoring"],
        profile=_profile(),
        console=console,
    )
    out = console.export_text()
    assert "All stacks destroyed successfully" not in out
    assert "did not delete cleanly" in out
    assert "test-pool-monitoring" in out
    assert "delete-stack" in out


def test_summary_with_both_failed_resources_and_stacks():
    """A stack with enumerable DELETE_FAILED resources AND tracked failure shows both sections."""
    console = Console(record=True, width=120)
    DestroyCommand()._show_cleanup_summary(
        failed_resources=[
            {
                "logical_id": "DNSRecord",
                "resource_type": "AWS::Route53::RecordSet",
                "physical_id": "app.example.com",
                "status_reason": "client timeout",
            }
        ],
        retained_resources=[],
        stacks=["test-pool-monitoring"],
        profile=_profile(),
        console=console,
    )
    out = console.export_text()
    # Per-resource cleanup section is shown...
    assert "Manual cleanup required" in out
    assert "DNSRecord" in out
    # ...and the per-stack delete-stack guidance is still reached (not short-circuited).
    assert "delete-stack" in out
    assert "test-pool-monitoring" in out
    assert "All stacks destroyed successfully" not in out


def test_clean_run_still_reports_success():
    """No failures, no retained, no stacks -> success message preserved (no false negative)."""
    console = Console(record=True, width=120)
    DestroyCommand()._show_cleanup_summary([], [], [], _profile(), console)
    assert "All stacks destroyed successfully" in console.export_text()
