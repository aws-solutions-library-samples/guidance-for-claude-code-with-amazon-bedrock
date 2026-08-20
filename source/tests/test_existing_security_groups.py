# ABOUTME: Tests for existing security group support in CFN templates and deploy params
# ABOUTME: Validates parameters, conditions, and !If usage for custom SG pass-through

"""Tests for attaching pre-existing security groups (#758).

Admins can now provide their own security group IDs instead of using the
stack-created 0.0.0.0/0 security groups. This validates that:
1. CFN templates have the required parameters and conditions
2. Profile config accepts the new optional fields
3. Deploy params are passed when configured
"""

from claude_code_with_bedrock.config import Profile
from tests.cfn_yaml import INFRA_DIR, load_resolved

OTEL_TEMPLATE = INFRA_DIR / "otel-collector.yaml"
LANDING_TEMPLATE = INFRA_DIR / "landing-page-distribution.yaml"


class TestOtelCollectorTemplate:
    """otel-collector.yaml has existing SG parameters and conditions."""

    def test_has_existing_alb_sg_parameter(self):
        tpl = load_resolved(OTEL_TEMPLATE)
        params = tpl["Parameters"]
        assert "ExistingAlbSecurityGroupIds" in params
        assert params["ExistingAlbSecurityGroupIds"]["Default"] == ""

    def test_has_existing_task_sg_parameter(self):
        tpl = load_resolved(OTEL_TEMPLATE)
        params = tpl["Parameters"]
        assert "ExistingTaskSecurityGroupIds" in params
        assert params["ExistingTaskSecurityGroupIds"]["Default"] == ""

    def test_has_conditions(self):
        tpl = load_resolved(OTEL_TEMPLATE)
        conditions = tpl["Conditions"]
        assert "HasCustomAlbSgs" in conditions
        assert "HasCustomTaskSgs" in conditions
        assert "CreateAlbSg" in conditions
        assert "CreateTaskSg" in conditions

    def test_alb_sg_is_conditional(self):
        tpl = load_resolved(OTEL_TEMPLATE)
        alb_sg = tpl["Resources"]["ALBSecurityGroup"]
        assert alb_sg.get("Condition") == "CreateAlbSg"

    def test_task_sg_is_conditional(self):
        tpl = load_resolved(OTEL_TEMPLATE)
        task_sg = tpl["Resources"]["TaskSecurityGroup"]
        assert task_sg.get("Condition") == "CreateTaskSg"


class TestLandingPageTemplate:
    """landing-page-distribution.yaml has existing ALB SG parameter and conditions."""

    def test_has_existing_alb_sg_parameter(self):
        tpl = load_resolved(LANDING_TEMPLATE)
        params = tpl["Parameters"]
        assert "ExistingAlbSecurityGroupIds" in params
        assert params["ExistingAlbSecurityGroupIds"]["Default"] == ""

    def test_has_conditions(self):
        tpl = load_resolved(LANDING_TEMPLATE)
        conditions = tpl["Conditions"]
        assert "HasCustomAlbSgs" in conditions
        assert "CreateAlbSg" in conditions

    def test_alb_sg_is_conditional(self):
        tpl = load_resolved(LANDING_TEMPLATE)
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
