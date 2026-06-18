# ABOUTME: Tests that quota-monitoring.yaml includes execute-api:Invoke policy for IAM auth
# ABOUTME: Regression test for 403 error when IDC users call the quota API

"""Tests for quota API invoke policy in CloudFormation template."""

from pathlib import Path

import pytest
import yaml

TEMPLATE_PATH = Path(__file__).parent.parent.parent.parent / "deployment" / "infrastructure" / "quota-monitoring.yaml"


class TestQuotaApiInvokePolicy:
    """Verify quota-monitoring.yaml includes IAM policy for API Gateway access."""

    @pytest.fixture(autouse=True)
    def load_template(self):
        # Add CloudFormation intrinsic function constructors
        loader = yaml.SafeLoader
        loader.add_multi_constructor(
            "!",
            lambda loader, suffix, node: (
                loader.construct_scalar(node) if node.id == "scalar" else loader.construct_sequence(node)
            ),
        )
        with open(TEMPLATE_PATH) as f:
            self.template = yaml.load(f, Loader=loader)
        self.resources = self.template.get("Resources", {})
        self.outputs = self.template.get("Outputs", {})

    def test_invoke_policy_resource_exists(self):
        """Template must include a QuotaApiInvokePolicy managed policy."""
        assert "QuotaApiInvokePolicy" in self.resources
        policy = self.resources["QuotaApiInvokePolicy"]
        assert policy["Type"] == "AWS::IAM::ManagedPolicy"

    def test_invoke_policy_grants_execute_api(self):
        """Policy must grant execute-api:Invoke action."""
        policy = self.resources["QuotaApiInvokePolicy"]
        doc = policy["Properties"]["PolicyDocument"]
        actions = []
        for stmt in doc["Statement"]:
            action = stmt.get("Action", "")
            if isinstance(action, list):
                actions.extend(action)
            else:
                actions.append(action)
        assert "execute-api:Invoke" in actions

    def test_invoke_policy_is_conditional_on_iam_auth(self):
        """Policy should only be created when using IAM auth (NoJwtAuth condition)."""
        policy = self.resources["QuotaApiInvokePolicy"]
        assert policy.get("Condition") == "NoJwtAuth"

    def test_invoke_policy_arn_output_exists(self):
        """Template must output the policy ARN for admins to attach."""
        assert "QuotaApiInvokePolicyArn" in self.outputs

    def test_invoke_policy_scoped_to_quota_api(self):
        """Policy resource must be scoped to the quota API (not wildcard)."""
        policy = self.resources["QuotaApiInvokePolicy"]
        doc = policy["Properties"]["PolicyDocument"]
        for stmt in doc["Statement"]:
            resource = stmt.get("Resource", "")
            # Should reference the specific API, not arn:aws:execute-api:*:*:*
            assert "QuotaCheckApi" in str(resource) or "${" in str(resource)
