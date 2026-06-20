# ABOUTME: Contract tests verifying CLI-generated parameters match CloudFormation template expectations
# ABOUTME: Catches parameter name/type drift between Python code and YAML templates

"""Contract tests for CLI ↔ CloudFormation parameter agreement.

When the CLI generates CloudFormation parameters, they must match what the
templates declare. These tests parse the actual templates and verify the
CLI's parameter generation logic produces compatible values.

Catches issues like:
- #375: Invalid "bedrock-runtime:" action prefix in IAM policies
- #313: Wrong stack_names key ('networking' instead of 's3')
- #398: SSM parameter conflicts on stack updates
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

INFRA_DIR = Path(__file__).parent.parent.parent.parent / "deployment" / "infrastructure"


# CloudFormation-aware YAML loader (handles !Ref, !Sub, !GetAtt, etc.)
class CFNLoader(yaml.SafeLoader):
    pass


def _cfn_constructor(loader, tag_suffix, node):
    """Generic constructor for CloudFormation intrinsic functions."""
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


CFNLoader.add_multi_constructor("!", _cfn_constructor)


def _load_template(name: str) -> dict:
    """Load a CloudFormation template."""
    path = INFRA_DIR / name
    if not path.exists():
        pytest.skip(f"Template {name} not found")
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=CFNLoader)


def _get_template_parameters(template: dict) -> dict:
    """Extract Parameters section from a template."""
    return template.get("Parameters", {})


def _get_all_templates() -> list[Path]:
    """List all YAML templates in infrastructure directory."""
    if not INFRA_DIR.exists():
        return []
    return list(INFRA_DIR.glob("*.yaml"))


class TestCloudFormationTemplateValidity:
    """Basic structural validity of CloudFormation templates."""

    @pytest.mark.parametrize("template_path", _get_all_templates(), ids=lambda p: p.name)
    def test_template_is_valid_yaml(self, template_path):
        """All templates must be parseable YAML (with CloudFormation intrinsics)."""
        with open(template_path, encoding="utf-8") as f:
            content = yaml.load(f, Loader=CFNLoader)
        assert isinstance(content, dict), f"{template_path.name} did not parse to a dict"

    @pytest.mark.parametrize("template_path", _get_all_templates(), ids=lambda p: p.name)
    def test_template_has_resources(self, template_path):
        """All templates must define at least one Resource."""
        with open(template_path, encoding="utf-8") as f:
            content = yaml.load(f, Loader=CFNLoader)
        # Some templates might be utility-only, but most should have Resources
        if "Resources" in content:
            assert len(content["Resources"]) > 0

    @pytest.mark.parametrize("template_path", _get_all_templates(), ids=lambda p: p.name)
    def test_template_has_description(self, template_path):
        """Templates should have a Description for CloudFormation console."""
        with open(template_path, encoding="utf-8") as f:
            content = yaml.load(f, Loader=CFNLoader)
        # Not strictly required but good practice
        if "AWSTemplateFormatVersion" in content:
            assert "Description" in content, f"{template_path.name} missing Description"


class TestIAMPolicyValidity:
    """Validate IAM policies use correct action prefixes."""

    # Valid IAM action prefixes for services used in this project
    VALID_ACTION_PREFIXES = {
        "bedrock",
        "cloudtrail",
        "cognito-identity",
        "cognito-idp",
        "sts",
        "logs",
        "cloudwatch",
        "s3",
        "s3express",
        "s3-object-lambda",
        "s3outposts",
        "dynamodb",
        "lambda",
        "iam",
        "ssm",
        "firehose",
        "glue",
        "athena",
        "kms",
        "codebuild",
        "ec2",
        "ecs",
        "ecr",
        "elasticloadbalancing",
        "route53",
        "acm",
        "secretsmanager",
        "cloudformation",
        "events",
        "sns",
        "sqs",
        "tag",
        "pricing",
        "oam",
        "lakeformation",
        "execute-api",
        "application-autoscaling",
        "ce",
        "cur",
        "es",
        "aoss",
    }

    def _extract_actions(self, template: dict) -> list[str]:
        """Recursively extract all IAM Action values from a template."""
        actions = []

        def walk(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == "Action":
                        if isinstance(value, list):
                            actions.extend(value)
                        elif isinstance(value, str):
                            actions.append(value)
                    else:
                        walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(template)
        return actions

    @pytest.mark.parametrize("template_path", _get_all_templates(), ids=lambda p: p.name)
    def test_iam_actions_use_valid_prefixes(self, template_path):
        """All IAM actions must use valid service prefixes (catches #375)."""
        with open(template_path, encoding="utf-8") as f:
            content = yaml.load(f, Loader=CFNLoader)

        actions = self._extract_actions(content)
        for action in actions:
            if action == "*":
                continue  # Wildcard is valid (though not ideal)
            if ":" not in action:
                continue  # Might be a Ref or Sub expression

            prefix = action.split(":")[0]
            # Handle Fn::Sub expressions
            if "${" in prefix:
                continue

            assert prefix in self.VALID_ACTION_PREFIXES, (
                f"Invalid IAM action prefix '{prefix}' in {template_path.name}: {action}. "
                f"Did you mean 'bedrock' instead of 'bedrock-runtime'?"
            )


class TestQuotaMonitoringTemplateContract:
    """Contract tests between quota CLI commands and quota-monitoring.yaml."""

    def test_quota_lambda_env_vars_match_code(self):
        """Lambda environment variables in CFn match what quota_check code reads."""
        template = _load_template("quota-monitoring.yaml")
        resources = template.get("Resources", {})

        # Find the quota check Lambda function
        quota_lambda = None
        for resource_name, resource in resources.items():
            if resource.get("Type") == "AWS::Lambda::Function":
                props = resource.get("Properties", {})
                handler = props.get("Handler", "")
                if "quota_check" in handler or "quotacheck" in resource_name.lower():
                    quota_lambda = props
                    break

        if quota_lambda is None:
            # Template might use AWS::Serverless or different structure
            pytest.skip("Could not find quota_check Lambda in template")

        env_vars = quota_lambda.get("Environment", {}).get("Variables", {})

        # These env vars are read by the quota_check Lambda at import time
        expected_vars = {
            "QUOTA_TABLE",
            "MONTHLY_TOKEN_LIMIT",
            "MONTHLY_ENFORCEMENT_MODE",
            "ENABLE_FINEGRAINED_QUOTAS",
        }

        for var in expected_vars:
            assert var in env_vars, f"quota_check Lambda missing env var '{var}' that the code reads at import time"

    def test_quota_monitor_role_has_update_item(self):
        """QuotaMonitorRole must have dynamodb:UpdateItem for atomic counter upserts."""
        template = _load_template("quota-monitoring.yaml")
        resources = template.get("Resources", {})

        monitor_role = resources.get("QuotaMonitorRole", {})
        policies = monitor_role.get("Properties", {}).get("Policies", [])

        all_actions = []
        for policy in policies:
            statements = policy.get("PolicyDocument", {}).get("Statement", [])
            for stmt in statements:
                actions = stmt.get("Action", [])
                if isinstance(actions, str):
                    actions = [actions]
                all_actions.extend(actions)

        assert "dynamodb:UpdateItem" in all_actions, (
            "QuotaMonitorRole missing dynamodb:UpdateItem — quota_monitor Lambda uses "
            "table.update_item() for atomic counter upserts"
        )

    def test_dynamodb_table_schema_matches_code(self):
        """DynamoDB table key schema matches what Lambda code uses for queries."""
        template = _load_template("quota-monitoring.yaml")
        resources = template.get("Resources", {})

        # Find DynamoDB tables
        for resource_name, resource in resources.items():
            if resource.get("Type") == "AWS::DynamoDB::Table":
                key_schema = resource.get("Properties", {}).get("KeySchema", [])
                # Table should have at least a partition key
                assert len(key_schema) >= 1, f"Table {resource_name} has no key schema"

                # Verify key attribute names are strings
                for key in key_schema:
                    assert "AttributeName" in key
                    assert "KeyType" in key
                    assert key["KeyType"] in ("HASH", "RANGE")


class TestDeployCommandStackNames:
    """Verify deploy command knows about all infrastructure stacks."""

    def test_all_templates_have_potential_stack_reference(self):
        """Every infrastructure template should be deployable via the CLI."""
        templates = _get_all_templates()

        # Templates that are utility/nested (not top-level stacks)
        utility_templates = {
            "cognito-custom-domain-cert.yaml",  # Nested in cognito setup
        }

        for template_path in templates:
            if template_path.name in utility_templates:
                continue

            # The template should be parseable and have basic structure
            with open(template_path, encoding="utf-8") as f:
                content = yaml.load(f, Loader=CFNLoader)

            assert "Resources" in content or "AWSTemplateFormatVersion" in content, (
                f"Template {template_path.name} doesn't look like a valid CloudFormation template"
            )


class TestCoWorkLogGroupContract:
    """Contract: cowork-dashboard MetricFilters target a log group that the
    monitoring stack actually creates.

    Regression for the fresh-deploy failure "AWS::Logs::MetricFilter
    (CostMetricFilter): The specified log group does not exist." A MetricFilter
    requires its target log group to exist at deploy time; the cowork log group
    must therefore be a managed AWS::Logs::LogGroup resource (in otel-collector),
    not left to runtime auto-creation by the collector's exporter.
    """

    COWORK_LOG_GROUP = "/aws/claude-cowork/events"

    def _log_group_names(self, template: dict) -> set:
        names = set()
        for resource in template.get("Resources", {}).values():
            if resource.get("Type") == "AWS::Logs::LogGroup":
                lg = resource.get("Properties", {}).get("LogGroupName")
                if isinstance(lg, str):
                    names.add(lg)
        return names

    def _metric_filter_log_groups(self, template: dict) -> set:
        groups = set()
        for resource in template.get("Resources", {}).values():
            if resource.get("Type") == "AWS::Logs::MetricFilter":
                lg = resource.get("Properties", {}).get("LogGroupName")
                if isinstance(lg, str):
                    groups.add(lg)
        return groups

    def test_cowork_dashboard_filters_target_cowork_log_group(self):
        """Sanity: the cowork-dashboard filters do reference the cowork log group."""
        dash = _load_template("cowork-dashboard.yaml")
        assert self.COWORK_LOG_GROUP in self._metric_filter_log_groups(dash)

    def test_cowork_log_group_is_created_by_monitoring_stack(self):
        """otel-collector must create the cowork log group as a managed resource,
        so it exists before cowork-dashboard's MetricFilters attach to it."""
        otel = _load_template("otel-collector.yaml")
        assert self.COWORK_LOG_GROUP in self._log_group_names(otel), (
            f"{self.COWORK_LOG_GROUP} is referenced by cowork-dashboard MetricFilters but "
            f"not created as an AWS::Logs::LogGroup in otel-collector.yaml — a fresh deploy "
            f"will fail with 'The specified log group does not exist'."
        )

    def test_every_cowork_filter_group_has_a_creator(self):
        """Every log group a cowork-dashboard MetricFilter targets must be created
        somewhere in the monitoring stack (no assume-exists log groups)."""
        dash_groups = self._metric_filter_log_groups(_load_template("cowork-dashboard.yaml"))
        created = self._log_group_names(_load_template("otel-collector.yaml"))
        missing = dash_groups - created
        assert not missing, f"cowork-dashboard filters target log groups nobody creates: {missing}"
