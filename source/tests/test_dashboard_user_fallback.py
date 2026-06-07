"""Regression test for issue #365: dashboard widgets must not hard-filter on user.email only."""

import json
from pathlib import Path

import yaml


INFRA_DIR = Path(__file__).resolve().parents[2] / "deployment" / "infrastructure"


# Custom YAML loader for CloudFormation intrinsic functions
class CfnLoader(yaml.SafeLoader):
    pass


def _cfn_tag_constructor(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)


CfnLoader.add_multi_constructor("!", _cfn_tag_constructor)


class TestDashboardUserFallback:
    """Dashboard widgets must group by both user.email and user.id for resilience."""

    def _get_dashboard_body(self):
        """Extract the dashboard JSON body from the CloudFormation template."""
        template_path = INFRA_DIR / "claude-code-dashboard.yaml"
        with open(template_path, encoding="utf-8") as f:
            template = yaml.load(f, Loader=CfnLoader)

        # Find the dashboard resource
        for name, resource in template.get("Resources", {}).items():
            if resource.get("Type") == "AWS::CloudWatch::Dashboard":
                body = resource.get("Properties", {}).get("DashboardBody", "")
                if isinstance(body, str):
                    return body
        return ""

    def test_active_users_widget_includes_user_id(self):
        """Active Users widget must group by user.id (not just user.email)."""
        body = self._get_dashboard_body()
        # Check that any group by clause includes user.id
        assert "user.id" in body, (
            "Dashboard must include user.id in group-by clauses. "
            "Without this, users whose OTEL stream lacks user.email "
            "(e.g., no otel-helper installed) are invisible in dashboards. "
            "See issue #365."
        )

    def test_no_exclusive_user_email_grouping(self):
        """No widget should group ONLY by user.email without user.id fallback."""
        body = self._get_dashboard_body()
        # Find all group by / sum by clauses
        import re
        # Match: group by ("user.email") or sum by ("user.email") WITHOUT user.id
        exclusive_patterns = re.findall(
            r'(?:group|sum) by \(\\"user\.email\\"\)(?!\s*,\s*\\"user\.id\\")',
            body
        )
        assert len(exclusive_patterns) == 0, (
            f"Found {len(exclusive_patterns)} widget(s) that group exclusively by "
            f"user.email without user.id fallback. This causes widgets to show 0 "
            f"when otel-helper is not installed. See issue #365."
        )
