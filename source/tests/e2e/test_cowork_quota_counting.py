# ABOUTME: Tests that quota_monitor aggregates CoWork 3P usage alongside Claude Code
# ABOUTME: Regression test for CoWork tokens not counting toward per-user quota

"""Tests for CoWork 3P quota counting in quota_monitor Lambda."""

from tests.cfn_yaml import INFRA_DIR, REPO_ROOT, load_resolved


class TestCoWorkQuotaCounting:
    """Verify quota_monitor queries ClaudeCoWork namespace and merges usage."""

    def test_quota_monitor_has_cowork_promql_query(self):
        """The quota_monitor Lambda must query ClaudeCoWork namespace metrics."""
        lambda_path = INFRA_DIR / "lambda-functions" / "quota_monitor" / "index.py"
        content = lambda_path.read_text(encoding="utf-8")
        assert "ClaudeCoWork" in content, "quota_monitor must query ClaudeCoWork namespace"
        assert "token.usage.input" in content, "quota_monitor must query CoWork input tokens"
        assert "token.usage.output" in content, "quota_monitor must query CoWork output tokens"
        assert "user_email" in content, "quota_monitor must group CoWork metrics by user_email"

    def test_cowork_query_is_non_fatal(self):
        """CoWork PromQL failure must not crash quota monitoring."""
        lambda_path = INFRA_DIR / "lambda-functions" / "quota_monitor" / "index.py"
        content = lambda_path.read_text(encoding="utf-8")
        # The CoWork query must be wrapped in try/except
        assert "non-fatal" in content.lower() or "non_fatal" in content.lower() or "optional" in content.lower(), (
            "CoWork PromQL query must be wrapped in try/except with non-fatal handling"
        )

    def test_cowork_dashboard_has_user_email_dimension(self):
        """CoWork metric filters must include user_email dimension for per-user attribution."""
        template = load_resolved(INFRA_DIR / "cowork-dashboard.yaml")

        resources = template.get("Resources", {})
        api_request_filters = [
            (name, res)
            for name, res in resources.items()
            if res.get("Type") == "AWS::Logs::MetricFilter"
            and "claude_code.api_request" in res.get("Properties", {}).get("FilterPattern", "")
        ]

        assert len(api_request_filters) >= 6, "Expected at least 6 api_request metric filters"

        for name, res in api_request_filters:
            transforms = res["Properties"]["MetricTransformations"]
            for t in transforms:
                dims = t.get("Dimensions", [])
                dim_keys = [d.get("Key", "") for d in dims]
                assert "user_email" in dim_keys, (
                    f"{name}: MetricFilter must have user_email dimension for quota counting"
                )

    def test_cowork_docs_mention_quota_enforcement(self):
        """COWORK_3P.md must document quota enforcement behavior."""
        docs_path = REPO_ROOT / "assets" / "docs" / "COWORK_3P.md"
        content = docs_path.read_text(encoding="utf-8")
        assert "## Quota Enforcement" in content
        assert "credential-process" in content
        assert "credential refresh" in content.lower() or "refresh cycle" in content.lower()
