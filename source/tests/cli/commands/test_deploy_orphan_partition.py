# ABOUTME: Tests that the orphaned-stack check never probes across partitions and
# ABOUTME: never aborts a deploy on network/SSL failures (advisory check only).

"""Orphaned-stack check partition/resilience regression tests.

The check probes CloudFormation for every stack type NOT in the deploy plan.
websearch defaults to us-east-1 (the connector is commercial-only), so a
GovCloud deploy probed a commercial-partition endpoint — unreachable in
typical GovCloud/air-gapped environments, surfacing as an SSL error that
crashed `ccwb deploy` right after the deployment plan printed
(get_stack_status only handles ClientError, so connection errors propagate).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile


class _NullConsole:
    def print(self, *args, **kwargs):
        pass


def _profile(region: str) -> Profile:
    return Profile(
        name="orphan-test",
        provider_domain="company.okta.com",
        client_id="client-123",
        credential_storage="session",
        aws_region=region,
        identity_pool_name="orphan-pool",
        auth_type="oidc",
        monitoring_enabled=True,
        monitoring_mode="sidecar",
    )


def _run_check(profile, cf_manager, deploying=(("auth", "x"), ("dashboard", "x"))):
    return DeployCommand()._check_orphaned_stacks(list(deploying), profile, cf_manager, _NullConsole())


class TestCrossPartitionProbing:
    def test_govcloud_deploy_never_probes_commercial_regions(self):
        """The regression: websearch's home region is us-east-1, a different
        PARTITION from a GovCloud profile — no client may be created for it
        and no status call may be made against it."""
        cf_manager = MagicMock()
        cf_manager.get_stack_status.return_value = None

        with patch("claude_code_with_bedrock.cli.commands.deploy.CloudFormationManager") as manager_cls:
            _run_check(_profile("us-gov-west-1"), cf_manager)

        cross_partition = [call for call in manager_cls.call_args_list if "us-gov" not in call.kwargs.get("region", "")]
        assert not cross_partition, f"probed commercial regions from GovCloud: {cross_partition}"

    def test_commercial_deploy_still_probes_websearch_region(self):
        """Same-partition cross-region checks must keep working (that's how
        cross-region websearch/codebuild orphans are detected at all)."""
        cf_manager = MagicMock()
        cf_manager.get_stack_status.return_value = None

        with patch("claude_code_with_bedrock.cli.commands.deploy.CloudFormationManager") as manager_cls:
            manager_cls.return_value.get_stack_status.return_value = None
            _run_check(_profile("us-west-2"), cf_manager)

        probed_regions = [call.kwargs.get("region") for call in manager_cls.call_args_list]
        assert "us-east-1" in probed_regions, f"websearch region not probed: {probed_regions}"


class TestAdvisoryCheckResilience:
    def test_connection_errors_do_not_abort_deploy(self):
        """get_stack_status raising (SSL/connect errors are not ClientError)
        must degrade to a skipped check, not a crashed deploy."""
        cf_manager = MagicMock()
        cf_manager.get_stack_status.side_effect = OSError("SSL: CERTIFICATE_VERIFY_FAILED")

        orphaned = _run_check(_profile("us-gov-west-1"), cf_manager)
        assert orphaned == []

    def test_orphans_still_detected(self):
        cf_manager = MagicMock()
        cf_manager.get_stack_status.side_effect = lambda name: "CREATE_COMPLETE" if name.endswith("-quota") else None

        orphaned = _run_check(_profile("us-gov-west-1"), cf_manager)
        assert ("quota", "orphan-pool-quota", "CREATE_COMPLETE") in orphaned
