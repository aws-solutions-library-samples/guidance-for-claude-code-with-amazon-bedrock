# ABOUTME: Integration tests that validate a real AWS deployment
# ABOUTME: Only runs when E2E_ACTIVE=true (nightly CI or manual trigger)

"""Integration tests for deployed infrastructure.

These tests run against a real AWS deployment and validate:
- CloudFormation stacks are healthy
- Quota monitoring is operational
- Stack outputs are well-formed
- Destroy command cleans up everything

Skip unless E2E_ACTIVE=true environment variable is set.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Skip entire module if not in E2E mode
pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_ACTIVE") != "true",
    reason="E2E tests only run when E2E_ACTIVE=true (nightly CI)"
)


def _run_aws(args: list[str]) -> dict | str:
    """Run an AWS CLI command and return parsed JSON or raw output."""
    result = subprocess.run(
        ["aws"] + args + ["--output", "json"],
        capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        pytest.fail(f"AWS CLI failed: {result.stderr}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip()


def _run_ccwb(args: list[str]) -> subprocess.CompletedProcess:
    """Run a ccwb command."""
    result = subprocess.run(
        ["poetry", "run", "ccwb"] + args,
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(Path(__file__).parent.parent.parent / "source")
    )
    return result


class TestDeploymentHealth:
    """Validate deployed infrastructure is healthy."""

    def test_stacks_exist_and_healthy(self):
        """At least one ccwb/claude-code stack should be in CREATE_COMPLETE."""
        data = _run_aws([
            "cloudformation", "list-stacks",
            "--stack-status-filter", "CREATE_COMPLETE", "UPDATE_COMPLETE"
        ])

        stack_names = [
            s["StackName"] for s in data.get("StackSummaries", [])
            if s["StackName"].startswith(("ccwb-", "claude-code-"))
        ]

        assert len(stack_names) > 0, "No ccwb/claude-code stacks found after deploy"

    def test_no_failed_stacks(self):
        """No ccwb stacks should be in FAILED or ROLLBACK state."""
        data = _run_aws([
            "cloudformation", "list-stacks",
            "--stack-status-filter",
            "CREATE_FAILED", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED",
            "UPDATE_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED"
        ])

        failed_stacks = [
            s["StackName"] for s in data.get("StackSummaries", [])
            if s["StackName"].startswith(("ccwb-", "claude-code-"))
        ]

        assert len(failed_stacks) == 0, f"Failed stacks found: {failed_stacks}"

    def test_ccwb_status_reports_deployment(self):
        """ccwb status should report a deployment exists."""
        result = _run_ccwb(["status"])
        assert result.returncode == 0, f"ccwb status failed: {result.stderr}"
        # Status should mention the deployed region or stack
        output = result.stdout + result.stderr
        assert "us-east-1" in output or "deployed" in output.lower() or "active" in output.lower()


class TestQuotaInfrastructure:
    """Validate quota monitoring stack is operational."""

    def test_quota_table_exists(self):
        """DynamoDB quota table should exist after deploy."""
        data = _run_aws(["dynamodb", "list-tables"])
        tables = data.get("TableNames", [])

        quota_tables = [t for t in tables if "quota" in t.lower()]
        # Quota tables should exist if quota_monitoring_enabled=true
        assert len(quota_tables) > 0, (
            f"No quota tables found. Available: {tables}"
        )

    def test_quota_lambda_exists(self):
        """quota_check Lambda should be deployed."""
        data = _run_aws(["lambda", "list-functions"])
        functions = data.get("Functions", [])

        quota_functions = [
            f["FunctionName"] for f in functions
            if "quota" in f["FunctionName"].lower()
        ]

        assert len(quota_functions) > 0, "No quota Lambda functions found"

    def test_quota_lambda_invocable(self):
        """quota_check Lambda should respond to a test invocation."""
        # Find the quota check function
        data = _run_aws(["lambda", "list-functions"])
        functions = data.get("Functions", [])
        quota_fn = next(
            (f["FunctionName"] for f in functions if "quota_check" in f["FunctionName"].lower()),
            None
        )

        if quota_fn is None:
            pytest.skip("quota_check Lambda not found")

        # Invoke with a test event
        test_event = json.dumps({
            "requestContext": {
                "authorizer": {
                    "jwt": {
                        "claims": {"email": "e2e-test@ci.internal"}
                    }
                }
            }
        })

        result = subprocess.run(
            ["aws", "lambda", "invoke",
             "--function-name", quota_fn,
             "--payload", test_event,
             "/tmp/lambda-response.json"],
            capture_output=True, text=True, encoding="utf-8"
        )

        assert result.returncode == 0, f"Lambda invoke failed: {result.stderr}"

        with open("/tmp/lambda-response.json", encoding="utf-8") as f:
            response = json.load(f)

        assert "statusCode" in response or "body" in response or "FunctionError" not in result.stdout


class TestBedrockAccess:
    """Validate Bedrock is accessible with the deployed role."""

    def test_bedrock_converse(self):
        """Can invoke Bedrock Converse API with deployed credentials."""
        result = subprocess.run(
            ["aws", "bedrock-runtime", "converse",
             "--model-id", "us.anthropic.claude-sonnet-4-20250514-v1:0",
             "--messages", json.dumps([{
                 "role": "user",
                 "content": [{"text": "Reply with exactly: E2E_OK"}]
             }]),
             "--max-tokens", "10",
             "--region", "us-east-1",
             "--output", "json"],
            capture_output=True, text=True, encoding="utf-8"
        )

        assert result.returncode == 0, f"Bedrock invoke failed: {result.stderr}"
        response = json.loads(result.stdout)
        assert "output" in response


class TestDestroyCleanup:
    """Validate destroy command cleans up all resources."""

    def test_destroy_completes(self):
        """ccwb destroy should complete without errors."""
        result = _run_ccwb(["destroy", "--yes"])
        # destroy may warn about retained buckets but should not crash
        assert result.returncode == 0, f"ccwb destroy failed: {result.stderr}"

    def test_no_stacks_remain(self):
        """After destroy, no ccwb stacks should remain."""
        data = _run_aws([
            "cloudformation", "list-stacks",
            "--stack-status-filter", "CREATE_COMPLETE", "UPDATE_COMPLETE"
        ])

        remaining = [
            s["StackName"] for s in data.get("StackSummaries", [])
            if s["StackName"].startswith(("ccwb-", "claude-code-"))
        ]

        assert len(remaining) == 0, f"Stacks not cleaned up: {remaining}"
