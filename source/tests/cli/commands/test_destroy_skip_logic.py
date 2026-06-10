# ABOUTME: Behavioral tests for destroy command skip-guard logic
# ABOUTME: Drives DestroyCommand and asserts which stacks are actually deleted

"""Behavioral tests for `ccwb destroy` stack selection and skip guards.

Where test_destroy_stacks.py checks the static DESTROYABLE_STACKS data, these
tests run the command end-to-end (mocking the profile and the actual CFN delete)
and assert which stacks `_delete_stack` is called for under each profile shape.
A removed or broken skip guard fails one of these.
"""

from unittest.mock import Mock, patch

from cleo.testers.command_tester import CommandTester

from claude_code_with_bedrock.cli.commands.destroy import DestroyCommand


def _profile(**overrides):
    """A mock profile with sensible defaults; override per test."""
    p = Mock()
    p.identity_pool_name = "test-pool"
    p.stack_names = {}
    p.monitoring_enabled = True
    p.monitoring_mode = "central"
    p.quota_monitoring_enabled = False
    p.enable_distribution = False
    p.enable_codebuild = False
    p.aws_region = "us-east-1"
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _run_destroy(profile, stack_arg=None):
    """Run `destroy --force` with a mocked profile; return the set of stacks
    `_delete_stack` was actually invoked for."""
    deleted = []

    with (
        patch("claude_code_with_bedrock.cli.commands.destroy.Config") as MockConfig,
        patch.object(DestroyCommand, "_delete_stack", return_value=0) as mock_delete,
        patch.object(DestroyCommand, "_get_failed_resources", return_value=[]),
        patch.object(DestroyCommand, "_show_cleanup_summary"),
    ):
        MockConfig.load.return_value.get_profile.return_value = profile
        MockConfig.load.return_value.active_profile = "test"

        # _delete_stack(self, stack_name, region, console) -> record the stack_name
        mock_delete.side_effect = lambda stack_name, region, console: deleted.append(stack_name) or 0

        command = DestroyCommand()
        tester = CommandTester(command)
        args = "--force"
        if stack_arg:
            args = f"{stack_arg} --force"
        exit_code = tester.execute(args)

    # Map stack_names (test-pool-<stack>) back to stack keys for readability.
    return exit_code, {name.replace("test-pool-", "") for name in deleted}


class TestSkipGuards:
    def test_distribution_deleted_only_when_enabled(self):
        _, with_it = _run_destroy(_profile(enable_distribution=True))
        assert "distribution" in with_it

        _, without_it = _run_destroy(_profile(enable_distribution=False))
        assert "distribution" not in without_it

    def test_codebuild_deleted_only_when_enabled(self):
        _, with_it = _run_destroy(_profile(enable_codebuild=True))
        assert "codebuild" in with_it

        _, without_it = _run_destroy(_profile(enable_codebuild=False))
        assert "codebuild" not in without_it

    def test_monitoring_stacks_skipped_when_monitoring_disabled(self):
        _, deleted = _run_destroy(_profile(monitoring_enabled=False))
        for stack in ("monitoring", "dashboard", "networking", "analytics", "s3bucket"):
            assert stack not in deleted, f"{stack} should be skipped when monitoring disabled"
        # auth always destroyed
        assert "auth" in deleted

    def test_sidecar_mode_skips_ecs_stacks(self):
        _, deleted = _run_destroy(_profile(monitoring_enabled=True, monitoring_mode="sidecar"))
        for stack in ("networking", "monitoring", "analytics", "s3bucket"):
            assert stack not in deleted, f"{stack} should be skipped in sidecar mode"

    def test_quota_deleted_only_when_enabled(self):
        _, with_it = _run_destroy(_profile(quota_monitoring_enabled=True))
        assert "quota" in with_it
        _, without_it = _run_destroy(_profile(quota_monitoring_enabled=False))
        assert "quota" not in without_it

    def test_full_profile_deletes_new_stacks(self):
        # A profile with everything on must tear down distribution AND codebuild
        # (the two stacks this PR adds) -- the orphaned-stack regression.
        _, deleted = _run_destroy(
            _profile(enable_distribution=True, enable_codebuild=True, quota_monitoring_enabled=True)
        )
        assert {"distribution", "codebuild"} <= deleted


class TestSingleStackArg:
    def test_distribution_arg_accepted(self):
        exit_code, deleted = _run_destroy(_profile(enable_distribution=True), stack_arg="distribution")
        assert exit_code == 0
        assert deleted == {"distribution"}

    def test_codebuild_arg_accepted(self):
        exit_code, deleted = _run_destroy(_profile(enable_codebuild=True), stack_arg="codebuild")
        assert exit_code == 0
        assert deleted == {"codebuild"}

    def test_unknown_stack_arg_rejected(self):
        exit_code, deleted = _run_destroy(_profile(), stack_arg="nonexistent")
        assert exit_code == 1
        assert deleted == set()
