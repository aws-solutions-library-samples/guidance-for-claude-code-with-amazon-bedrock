# ABOUTME: Tests for the bypass-detection Lambda's identity extraction and telemetry freshness logic
# ABOUTME: Covers ARN->email parsing and the per-user GetItem freshness check (Option C, no scan)

"""Tests for the sidecar bypass-detection Lambda."""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock


LAMBDA_PATH = (
    Path(__file__).resolve().parents[2]
    / "deployment"
    / "infrastructure"
    / "lambda-functions"
    / "sidecar_monitor"
    / "index.py"
)


def _load_module() -> object:
    """Load the bypass-detection Lambda module fresh.

    Client construction is lazy (no network calls), so import succeeds without
    AWS credentials.
    """
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    module_name = "sidecar_monitor_index"
    spec = importlib.util.spec_from_file_location(module_name, LAMBDA_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


index = _load_module()


# ---------------------------------------------------------------------------
# ARN -> email extraction
# ---------------------------------------------------------------------------


class TestExtractEmailFromArn:
    def test_assumed_role_with_email_session(self):
        arn = "arn:aws:sts::123456789012:assumed-role/ClaudeCodeRole/alice@example.com"
        assert index._extract_email_from_arn(arn) == "alice@example.com"

    def test_lowercases_email(self):
        arn = "arn:aws:sts::123456789012:assumed-role/ClaudeCodeRole/Alice@Example.COM"
        assert index._extract_email_from_arn(arn) == "alice@example.com"

    def test_non_email_session_name_ignored(self):
        arn = "arn:aws:sts::123456789012:assumed-role/ClaudeCodeRole/claude-code-abc123"
        assert index._extract_email_from_arn(arn) is None

    def test_non_assumed_role_arn_ignored(self):
        arn = "arn:aws:iam::123456789012:user/some-user"
        assert index._extract_email_from_arn(arn) is None

    def test_empty_or_none_arn(self):
        assert index._extract_email_from_arn("") is None
        assert index._extract_email_from_arn(None) is None


# ---------------------------------------------------------------------------
# Per-user telemetry freshness (Option C: point GetItem, no scan)
# ---------------------------------------------------------------------------


class TestIsReportingTelemetry:
    def _set_item(self, item):
        """Patch the module's quota_table.get_item to return the given Item."""
        index.quota_table = MagicMock()
        index.quota_table.get_item.return_value = {"Item": item} if item is not None else {}

    def test_fresh_timestamp_is_reporting(self):
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=15)
        self._set_item({"last_updated": now.isoformat()})
        assert index.is_reporting_telemetry("alice@example.com", window_start) is True

    def test_stale_timestamp_not_reporting(self):
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=15)
        old = (now - timedelta(hours=2)).isoformat()
        self._set_item({"last_updated": old})
        assert index.is_reporting_telemetry("bob@example.com", window_start) is False

    def test_missing_record_not_reporting(self):
        window_start = datetime.now(timezone.utc) - timedelta(minutes=15)
        self._set_item(None)  # no DynamoDB item at all => sidecar stopped
        assert index.is_reporting_telemetry("carol@example.com", window_start) is False

    def test_item_without_last_updated_not_reporting(self):
        window_start = datetime.now(timezone.utc) - timedelta(minutes=15)
        self._set_item({"email": "dave@example.com"})
        assert index.is_reporting_telemetry("dave@example.com", window_start) is False

    def test_zulu_suffix_timestamp_parsed(self):
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=15)
        # quota_monitor writes timestamps with a trailing 'Z'
        self._set_item({"last_updated": now.isoformat().replace("+00:00", "Z")})
        assert index.is_reporting_telemetry("erin@example.com", window_start) is True

    def test_read_error_does_not_false_positive(self):
        window_start = datetime.now(timezone.utc) - timedelta(minutes=15)
        index.quota_table = MagicMock()
        index.quota_table.get_item.side_effect = RuntimeError("throttled")
        # On error we assume reporting (avoid false bypass alerts)
        assert index.is_reporting_telemetry("frank@example.com", window_start) is True


# ---------------------------------------------------------------------------
# lambda_handler integration tests (mocked boto3 clients)
# ---------------------------------------------------------------------------


class TestLambdaHandler:
    """Integration tests for the full lambda_handler flow."""

    def _mock_cloudtrail(self, events):
        """Mock CloudTrail paginator to return the given events."""
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Events": events}]
        index.cloudtrail = MagicMock()
        index.cloudtrail.get_paginator.return_value = mock_paginator

    def _mock_dynamodb(self, items_by_email):
        """Mock DynamoDB table to return items keyed by email."""
        def get_item_side_effect(**kwargs):
            pk = kwargs.get("Key", {}).get("pk", "")
            email = pk.replace("USER#", "")
            item = items_by_email.get(email)
            return {"Item": item} if item else {}

        index.quota_table = MagicMock()
        index.quota_table.get_item.side_effect = get_item_side_effect

    def _mock_cloudwatch(self):
        index.cloudwatch = MagicMock()

    def _mock_sns(self):
        index.sns_client = MagicMock()

    def _make_cloudtrail_event(self, email):
        """Create a mock CloudTrail event with assumed-role ARN."""
        import json
        return {
            "CloudTrailEvent": json.dumps({
                "userIdentity": {
                    "arn": f"arn:aws:sts::123456789012:assumed-role/ClaudeCodeRole/{email}"
                }
            })
        }

    def test_no_bypass_detected(self):
        """All Bedrock users are reporting telemetry → no alert."""
        now = datetime.now(timezone.utc)
        self._mock_cloudtrail([self._make_cloudtrail_event("alice@co.com")])
        self._mock_dynamodb({"alice@co.com": {"last_updated": now.isoformat()}})
        self._mock_cloudwatch()
        self._mock_sns()

        result = index.lambda_handler({}, None)

        import json
        body = json.loads(result["body"])
        assert body["sidecar_stopped_users"] == []
        assert body["bedrock_active_users"] == 1
        index.sns_client.publish.assert_not_called()

    def test_bypass_detected(self):
        """User active in CloudTrail but no DynamoDB record → alert fires."""
        self._mock_cloudtrail([self._make_cloudtrail_event("bob@co.com")])
        self._mock_dynamodb({})  # No records for bob
        self._mock_cloudwatch()
        self._mock_sns()
        # SNS_TOPIC_ARN is read at module level; patch the module attribute
        index.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123:test-topic"

        result = index.lambda_handler({}, None)

        import json
        body = json.loads(result["body"])
        assert "bob@co.com" in body["sidecar_stopped_users"]
        index.sns_client.publish.assert_called_once()
        call_kwargs = index.sns_client.publish.call_args[1]
        assert "bob@co.com" in call_kwargs["Message"]

        # Cleanup
        index.SNS_TOPIC_ARN = None

    def test_empty_window_no_alerts(self):
        """No CloudTrail events in window → no users, no alerts."""
        self._mock_cloudtrail([])
        self._mock_dynamodb({})
        self._mock_cloudwatch()
        self._mock_sns()

        result = index.lambda_handler({}, None)

        import json
        body = json.loads(result["body"])
        assert body["bedrock_active_users"] == 0
        assert body["sidecar_stopped_users"] == []
        index.sns_client.publish.assert_not_called()

    def test_mixed_users(self):
        """Some users reporting, some not → only non-reporters flagged."""
        now = datetime.now(timezone.utc)
        self._mock_cloudtrail([
            self._make_cloudtrail_event("alice@co.com"),
            self._make_cloudtrail_event("bob@co.com"),
            self._make_cloudtrail_event("carol@co.com"),
        ])
        self._mock_dynamodb({
            "alice@co.com": {"last_updated": now.isoformat()},
            # bob has no record
            "carol@co.com": {"last_updated": now.isoformat()},
        })
        self._mock_cloudwatch()
        self._mock_sns()
        index.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123:test-topic"

        result = index.lambda_handler({}, None)

        import json
        body = json.loads(result["body"])
        assert body["sidecar_stopped_users"] == ["bob@co.com"]
        assert body["bedrock_active_users"] == 3

        # Cleanup
        index.SNS_TOPIC_ARN = None
