# ABOUTME: Tests that cowork-dashboard.yaml metric filters match both CoWork schemas
# ABOUTME: Regression test for issue #541 gap 4 (metric filters don't match real events)

"""Tests for CoWork dashboard metric filter schema coverage."""

import json
import re
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
                tag, lambda l, n: l.construct_scalar(n) if n.id == "scalar" else l.construct_sequence(n)
            )
        loader.add_multi_constructor(
            "!", lambda l, suffix, n: l.construct_scalar(n) if n.id == "scalar" else l.construct_sequence(n)
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

    def test_no_filter_combines_dimensions_and_default_value(self):
        """DefaultValue and Dimensions are mutually exclusive in AWS::Logs::MetricFilter.

        Regression: CloudWatch Logs rejects a MetricTransformation that sets both
        ("dimensions and default value are mutually exclusive properties"), which
        broke `ccwb deploy` of the cowork-dashboard stack.
        """
        filters = self._get_filters()
        for name, res in filters.items():
            for transform in res["Properties"]["MetricTransformations"]:
                has_dimensions = "Dimensions" in transform
                has_default = "DefaultValue" in transform
                assert not (has_dimensions and has_default), (
                    f"{name}: MetricTransformation sets both Dimensions and DefaultValue; "
                    "they are mutually exclusive and CloudWatch Logs will reject the filter"
                )

    def test_all_filters_use_claude_cowork_namespace(self):
        """All filters must emit to ClaudeCoWork namespace."""
        filters = self._get_filters()
        for name, res in filters.items():
            for transform in res["Properties"]["MetricTransformations"]:
                assert transform["MetricNamespace"] == "ClaudeCoWork", (
                    f"{name}: expected ClaudeCoWork namespace, got {transform['MetricNamespace']}"
                )


class TestCoWorkDashboardBody:
    """Verify the CloudWatch DashboardBody widgets pass CloudWatch validation.

    Regression: PromQL queries (properties.data.queries) are only valid for the
    newer "chart" widget type. When such a query lived on a "metric" widget,
    CloudWatch rejected the dashboard with "Should have required property
    'metrics'" (18 validation errors), breaking `ccwb deploy` of the
    cowork-dashboard stack.
    """

    @pytest.fixture(autouse=True)
    def load_body(self):
        text = DASHBOARD_PATH.read_text()
        # Extract the DashboardBody block that follows `DashboardBody: !Sub |`
        marker = "DashboardBody: !Sub |"
        block = text[text.index(marker) :].splitlines()[1:]
        body_lines = []
        for line in block:
            if line.strip() == "":
                body_lines.append("")
            elif line.startswith("        "):
                body_lines.append(line[8:])
            else:
                break
        raw = "\n".join(body_lines)
        # Neutralize the !Sub variable so the block is parseable JSON.
        raw = re.sub(r"\$\{[^}]+\}", "us-east-1", raw)
        self.body = json.loads(raw)
        self.widgets = self.body["widgets"]

    def test_body_is_valid_json(self):
        """DashboardBody must be valid JSON (this fixture would raise otherwise)."""
        assert isinstance(self.widgets, list) and self.widgets

    def test_promql_queries_only_on_chart_widgets(self):
        """PromQL data.queries are only valid on 'chart' widgets, never 'metric'.

        A 'metric' widget carrying data.queries has neither a `metrics` array
        nor `annotations`, which CloudWatch rejects at deploy time.
        """
        for i, widget in enumerate(self.widgets):
            props = widget.get("properties", {})
            if "data" in props and "queries" in props["data"]:
                assert widget["type"] == "chart", (
                    f"widget {i} ({props.get('title')!r}) uses data.queries (PromQL) "
                    f"but has type {widget['type']!r}; PromQL requires type 'chart'"
                )

    def test_metric_widgets_have_metrics_array(self):
        """Every 'metric' widget must define a metrics array (CloudWatch requirement)."""
        for i, widget in enumerate(self.widgets):
            if widget["type"] == "metric":
                props = widget.get("properties", {})
                assert "metrics" in props, (
                    f"widget {i} ({props.get('title')!r}) is a metric widget without a "
                    "'metrics' array; CloudWatch will reject the dashboard"
                )

    def test_chart_widgets_do_not_use_metric_only_view_or_stacked(self):
        """Chart widgets use chart views (line/number/pie/bar), not metric-only keys.

        `singleValue`/`timeSeries` views and the top-level `stacked` flag belong to
        'metric' widgets; on a chart widget they are the fingerprint of a
        mis-typed PromQL widget.
        """
        metric_only_views = {"singleValue", "timeSeries"}
        for i, widget in enumerate(self.widgets):
            if widget["type"] == "chart":
                props = widget.get("properties", {})
                assert props.get("view") not in metric_only_views, (
                    f"widget {i} ({props.get('title')!r}) is a chart widget using "
                    f"metric-only view {props.get('view')!r}"
                )
                assert "stacked" not in props, (
                    f"widget {i} ({props.get('title')!r}) uses top-level 'stacked'; "
                    "chart widgets stack via plotOptions.style.lineOptions.stacked"
                )
