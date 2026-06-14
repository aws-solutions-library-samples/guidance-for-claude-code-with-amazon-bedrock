# ABOUTME: Regression tests for cross-region CodeBuild orphan detection in deploy
# ABOUTME: Ensures _check_orphaned_stacks queries the codebuild stack in its own region

"""A cross-region CodeBuild stack must be checked for orphan status in its own
region, not the main infrastructure region. Otherwise `ccwb deploy` checks the
wrong region, never finds the orphan, and never offers to delete it."""

from unittest.mock import MagicMock, patch

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand


def _profile(**overrides):
    p = MagicMock()
    p.identity_pool_name = "test-pool"
    p.stack_names = {}
    p.aws_region = "ap-southeast-1"
    p.codebuild_region = None
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def test_orphan_check_uses_codebuild_region_for_codebuild_stack():
    """When codebuild is cross-region, the orphan status check must hit that region."""
    profile = _profile(codebuild_region="us-east-1")
    main_mgr = MagicMock()
    main_mgr.get_stack_status.return_value = None  # nothing in main region

    # The region-specific manager built for codebuild reports an existing stack.
    cb_mgr = MagicMock()
    cb_mgr.get_stack_status.return_value = "CREATE_COMPLETE"

    captured_regions = []

    def _mgr_factory(region):
        captured_regions.append(region)
        return cb_mgr

    cmd = DeployCommand()
    # Deploy nothing, so every stack type is a candidate orphan.
    with patch("claude_code_with_bedrock.cli.commands.deploy.CloudFormationManager", side_effect=_mgr_factory):
        orphaned = cmd._check_orphaned_stacks([], profile, main_mgr, MagicMock())

    # A region-specific manager was built for us-east-1 (the codebuild region).
    assert "us-east-1" in captured_regions
    # codebuild is reported orphaned because it was found in us-east-1, not main.
    assert any(stack_type == "codebuild" for stack_type, _, _ in orphaned)


def test_orphan_check_no_extra_manager_when_codebuild_same_region():
    """No region-specific manager is built when codebuild uses the main region."""
    profile = _profile(codebuild_region=None)  # -> aws_region
    main_mgr = MagicMock()
    main_mgr.get_stack_status.return_value = None

    built = []
    cmd = DeployCommand()
    with patch(
        "claude_code_with_bedrock.cli.commands.deploy.CloudFormationManager",
        side_effect=lambda region: built.append(region) or MagicMock(),
    ):
        cmd._check_orphaned_stacks([], profile, main_mgr, MagicMock())

    # codebuild_region resolves to aws_region, so no separate manager is constructed.
    assert built == []
