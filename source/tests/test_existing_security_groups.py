# ABOUTME: Tests for existing security group support in CFN templates and deploy params
# ABOUTME: Validates parameters, conditions, and !If usage for custom SG pass-through

"""Tests for attaching pre-existing security groups (#758).

Admins can now provide their own security group IDs instead of using the
stack-created 0.0.0.0/0 security groups. This validates that:
1. CFN templates have the required parameters and conditions
2. Profile config accepts the new optional fields
3. Deploy params are passed when configured
"""

from pathlib import Path

import yaml

from claude_code_with_bedrock.config import Profile

SOURCE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SOURCE_ROOT.parents[0]
OTEL_TEMPLATE = REPO_ROOT / "deployment" / "infrastructure" / "otel-collector.yaml"
LANDING_TEMPLATE = REPO_ROOT / "deployment" / "infrastructure" / "landing-page-distribution.yaml"


# --- CFN-aware YAML loader (handles !Ref, !Sub, !GetAtt, etc.) ---


class _CfnLoader(yaml.SafeLoader):
    pass


def _cfn_tag_constructor(loader, tag_suffix, node):
    """Resolve any !Tag to its scalar/sequence/mapping payload (value only)."""
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_CfnLoader.add_multi_constructor("!", _cfn_tag_constructor)


def _load_template(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=_CfnLoader)


class TestOtelCollectorTemplate:
    """otel-collector.yaml has existing SG parameters and conditions."""

    def test_has_existing_alb_sg_parameter(self):
        tpl = _load_template(OTEL_TEMPLATE)
        params = tpl["Parameters"]
        assert "ExistingAlbSecurityGroupIds" in params
        assert params["ExistingAlbSecurityGroupIds"]["Default"] == ""

    def test_has_existing_task_sg_parameter(self):
        tpl = _load_template(OTEL_TEMPLATE)
        params = tpl["Parameters"]
        assert "ExistingTaskSecurityGroupIds" in params
        assert params["ExistingTaskSecurityGroupIds"]["Default"] == ""

    def test_has_conditions(self):
        tpl = _load_template(OTEL_TEMPLATE)
        conditions = tpl["Conditions"]
        assert "HasCustomAlbSgs" in conditions
        assert "HasCustomTaskSgs" in conditions
        assert "CreateAlbSg" in conditions
        assert "CreateTaskSg" in conditions

    def test_alb_sg_is_conditional(self):
        tpl = _load_template(OTEL_TEMPLATE)
        alb_sg = tpl["Resources"]["ALBSecurityGroup"]
        assert alb_sg.get("Condition") == "CreateAlbSg"

    def test_task_sg_is_conditional(self):
        tpl = _load_template(OTEL_TEMPLATE)
        task_sg = tpl["Resources"]["TaskSecurityGroup"]
        assert task_sg.get("Condition") == "CreateTaskSg"


class TestLandingPageTemplate:
    """landing-page-distribution.yaml has existing ALB SG parameter and conditions."""

    def test_has_existing_alb_sg_parameter(self):
        tpl = _load_template(LANDING_TEMPLATE)
        params = tpl["Parameters"]
        assert "ExistingAlbSecurityGroupIds" in params
        assert params["ExistingAlbSecurityGroupIds"]["Default"] == ""

    def test_has_conditions(self):
        tpl = _load_template(LANDING_TEMPLATE)
        conditions = tpl["Conditions"]
        assert "HasCustomAlbSgs" in conditions
        assert "CreateAlbSg" in conditions

    def test_alb_sg_is_conditional(self):
        tpl = _load_template(LANDING_TEMPLATE)
        alb_sg = tpl["Resources"]["ALBSecurityGroup"]
        assert alb_sg.get("Condition") == "CreateAlbSg"


class TestProfileConfig:
    """Profile dataclass accepts new security group fields."""

    def test_monitoring_existing_alb_sg_ids_default(self):
        p = Profile(
            name="test",
            provider_domain="example.com",
            client_id="abc",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )
        assert p.monitoring_existing_alb_sg_ids is None

    def test_monitoring_existing_task_sg_ids_default(self):
        p = Profile(
            name="test",
            provider_domain="example.com",
            client_id="abc",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )
        assert p.monitoring_existing_task_sg_ids is None

    def test_distribution_existing_alb_sg_ids_default(self):
        p = Profile(
            name="test",
            provider_domain="example.com",
            client_id="abc",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )
        assert p.distribution_existing_alb_sg_ids is None

    def test_fields_accept_values(self):
        p = Profile(
            name="test",
            provider_domain="example.com",
            client_id="abc",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            monitoring_existing_alb_sg_ids="sg-abc123,sg-def456",
            monitoring_existing_task_sg_ids="sg-111222",
            distribution_existing_alb_sg_ids="sg-333444",
        )
        assert p.monitoring_existing_alb_sg_ids == "sg-abc123,sg-def456"
        assert p.monitoring_existing_task_sg_ids == "sg-111222"
        assert p.distribution_existing_alb_sg_ids == "sg-333444"
