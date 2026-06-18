# ABOUTME: Tests that cowork-dashboard.yaml metric filters match both CoWork schemas
# ABOUTME: Regression test for issue #541 gap 4 (metric filters don't match real events)

"""Tests for CoWork dashboard metric filter schema coverage."""

from pathlib import Path

import pytest
import yaml

DASHBOARD_PATH = Path(__file__).parent.parent.parent.parent / "deployment" / "infrastructure" / "cowork-dashboard.yaml"


class TestCoWorkDashboardMetricFilters:
    """Verify metric filters cover both CoWork telemetry schemas."""

    @pytest.fixture(autouse=True)
    def load_template(self):
        # Add CloudFormation intrinsic function constructors
        loader = yaml.SafeLoader
        for tag in ["!Sub", "!Ref", "!GetAtt", "!If", "!Not", "!Equals", "!Select", "!Join", "!Split"]:
            loader.add_constructor(
                tag,
                lambda loader_inst, node: (
                    loader_inst.construct_scalar(node) if node.id == "scalar" else loader_inst.construct_sequence(node)
                ),
            )
        loader.add_multi_constructor(
            "!",
            lambda loader_inst, suffix, node: (
                loader_inst.construct_scalar(node) if node.id == "scalar" else loader_inst.construct_sequence(node)
            ),
        )
        with open(DASHBOARD_PATH) as f:
            self.template = yaml.load(f, Loader=loader)
        self.resources = self.template.get("Resources", {})

    def _get_filters(self):
        """Extract all MetricFilter resources."""
        return {name: res for name, res in self.resources.items() if res.get("Type") == "AWS::Logs::MetricFilter"}

    def test_has_api_request_schema_filters(self):
        """Dashboard should have filters for claude_code.api_request schema."""
        filters = self._get_filters()
        api_request_filters = [
            name for name, res in filters.items() if "claude_code.api_request" in res["Properties"]["FilterPattern"]
        ]
        # Should have input, output, cache_read, cache_creation, cost, sessions
        assert len(api_request_filters) >= 6, (
            f"Expected at least 6 api_request filters, got {len(api_request_filters)}: {api_request_filters}"
        )

    def test_has_lam_schema_filters(self):
        """Dashboard should have filters for lam_session_turn_completed schema."""
        filters = self._get_filters()
        lam_filters = [
            name for name, res in filters.items() if "lam_session_turn_completed" in res["Properties"]["FilterPattern"]
        ]
        assert len(lam_filters) >= 6, f"Expected at least 6 lam filters, got {len(lam_filters)}: {lam_filters}"

    def test_api_request_uses_top_level_attributes(self):
        """api_request schema uses $.attributes.* (not $.body.attributes.*)."""
        filters = self._get_filters()
        for name, res in filters.items():
            props = res["Properties"]
            if "claude_code.api_request" in props["FilterPattern"]:
                for transform in props["MetricTransformations"]:
                    value = transform["MetricValue"]
                    if value == "1":
                        continue  # session count uses literal
                    assert value.startswith("$.attributes."), (
                        f"{name}: api_request filter should use $.attributes.*, got {value}"
                    )
                    assert "body.attributes" not in value, (
                        f"{name}: api_request filter must NOT use $.body.attributes.*, got {value}"
                    )

    def test_lam_uses_body_attributes(self):
        """lam schema uses $.body.attributes.* (nested under body)."""
        filters = self._get_filters()
        for name, res in filters.items():
            props = res["Properties"]
            if "lam_session_turn_completed" in props["FilterPattern"]:
                for transform in props["MetricTransformations"]:
                    value = transform["MetricValue"]
                    if value == "1":
                        continue  # session count uses literal
                    assert value.startswith("$.body.attributes."), (
                        f"{name}: lam filter should use $.body.attributes.*, got {value}"
                    )

    def test_both_schemas_emit_same_metric_names(self):
        """Both schema filters should emit to the same CloudWatch metric names."""
        filters = self._get_filters()
        api_metrics = set()
        lam_metrics = set()
        for _name, res in filters.items():
            props = res["Properties"]
            for transform in props["MetricTransformations"]:
                metric_name = transform["MetricName"]
                if "claude_code.api_request" in props["FilterPattern"]:
                    api_metrics.add(metric_name)
                elif "lam_session_turn_completed" in props["FilterPattern"]:
                    lam_metrics.add(metric_name)
        assert api_metrics == lam_metrics, (
            f"Schema metric name mismatch:\n  api_request: {sorted(api_metrics)}\n  lam: {sorted(lam_metrics)}"
        )

    def test_all_filters_target_cowork_log_group(self):
        """All filters must target /aws/claude-cowork/events."""
        filters = self._get_filters()
        for name, res in filters.items():
            log_group = res["Properties"]["LogGroupName"]
            assert log_group == "/aws/claude-cowork/events", (
                f"{name}: expected /aws/claude-cowork/events, got {log_group}"
            )

    def test_all_filters_use_claude_cowork_namespace(self):
        """All filters must emit to ClaudeCoWork namespace."""
        filters = self._get_filters()
        for name, res in filters.items():
            for transform in res["Properties"]["MetricTransformations"]:
                assert transform["MetricNamespace"] == "ClaudeCoWork", (
                    f"{name}: expected ClaudeCoWork namespace, got {transform['MetricNamespace']}"
                )
