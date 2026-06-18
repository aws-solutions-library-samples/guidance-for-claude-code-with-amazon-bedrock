# ABOUTME: Tests for dual-auth quota check (JWT + IAM Identity Center)
# ABOUTME: Verifies identity resolution from both OIDC JWT claims and IAM caller ARN

"""Tests for quota_check Lambda dual identity resolution.

These tests verify the identity extraction logic ONLY — they don't test
the full quota calculation flow (that's tested in test_quota_check_lambda.py).
"""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Add the lambda function to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deployment", "infrastructure", "lambda-functions", "quota_check"))

import index


class TestIdentityResolution:
    """Test that the Lambda correctly extracts user identity from JWT or IAM ARN."""

    def _make_event(self, jwt_claims=None, caller_arn=None):
        """Build a mock API Gateway event."""
        event = {"requestContext": {}}
        if jwt_claims:
            event["requestContext"]["authorizer"] = {"jwt": {"claims": jwt_claims}}
        if caller_arn:
            event["requestContext"]["identity"] = {"caller": caller_arn, "userArn": caller_arn}
        return event

    def test_oidc_user_with_email_claim(self):
        """OIDC user: identity resolved from JWT email claim."""
        event = self._make_event(jwt_claims={"email": "alice@company.com", "sub": "abc123"})

        with patch.object(index, "resolve_quota_for_user") as mock_resolve, \
             patch.object(index, "get_unblock_status", return_value=None), \
             patch.object(index, "get_user_usage_summary", return_value={}):
            mock_resolve.return_value = {
                "monthly_limit": 225000000,
                "daily_limit": 0,
                "enforcement_mode": "alert",
                "enabled": True,
                "warning_threshold_80": 180000000,
                "warning_threshold_90": 202500000,
            }

            result = index.lambda_handler(event, None)
            body = json.loads(result["body"])

            mock_resolve.assert_called_once_with("alice@company.com", [])
            assert body["allowed"] is True

    def test_idc_user_with_email_in_arn(self):
        """IDC user: identity resolved from assumed-role ARN session name."""
        event = self._make_event(
            caller_arn="arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_BedrockAccess_abc123/bob@company.com"
        )

        with patch.object(index, "resolve_quota_for_user") as mock_resolve, \
             patch.object(index, "get_unblock_status", return_value=None), \
             patch.object(index, "get_user_usage_summary", return_value={}):
            mock_resolve.return_value = {
                "monthly_limit": 225000000,
                "daily_limit": 0,
                "enforcement_mode": "alert",
                "enabled": True,
                "warning_threshold_80": 180000000,
                "warning_threshold_90": 202500000,
            }

            result = index.lambda_handler(event, None)
            body = json.loads(result["body"])

            mock_resolve.assert_called_once_with("bob@company.com", [])
            assert body["allowed"] is True

    def test_idc_user_arn_without_email(self):
        """IDC user with ARN that has no email in session name — missing identity."""
        event = self._make_event(
            caller_arn="arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_BedrockAccess_abc123/session123"
        )

        result = index.lambda_handler(event, None)
        body = json.loads(result["body"])

        assert body["reason"] == "missing_identity"

    def test_no_auth_at_all(self):
        """No JWT claims and no IAM identity — missing identity."""
        event = self._make_event()

        result = index.lambda_handler(event, None)
        body = json.loads(result["body"])

        assert body["reason"] == "missing_identity"

    def test_jwt_without_email_falls_through_to_arn(self):
        """JWT present but missing email claim — falls through to IAM ARN."""
        event = self._make_event(
            jwt_claims={"sub": "abc123"},  # no email
            caller_arn="arn:aws:sts::123456789012:assumed-role/Role/carol@company.com"
        )

        with patch.object(index, "resolve_quota_for_user") as mock_resolve, \
             patch.object(index, "get_unblock_status", return_value=None), \
             patch.object(index, "get_user_usage_summary", return_value={}):
            mock_resolve.return_value = {
                "monthly_limit": 225000000,
                "daily_limit": 0,
                "enforcement_mode": "alert",
                "enabled": True,
                "warning_threshold_80": 180000000,
                "warning_threshold_90": 202500000,
            }

            result = index.lambda_handler(event, None)
            body = json.loads(result["body"])

            mock_resolve.assert_called_once_with("carol@company.com", [])
            assert body["allowed"] is True

    def test_malformed_arn_no_slash(self):
        """Malformed ARN without slashes — should not crash."""
        event = self._make_event(caller_arn="not-a-valid-arn")

        result = index.lambda_handler(event, None)
        body = json.loads(result["body"])

        # "not-a-valid-arn" split by "/" gives ["not-a-valid-arn"] — no @ → missing identity
        assert body["reason"] == "missing_identity"

    def test_jwt_preferred_over_arn_when_both_present(self):
        """When both JWT email and ARN are available, JWT takes priority."""
        event = self._make_event(
            jwt_claims={"email": "jwt-user@company.com", "sub": "abc"},
            caller_arn="arn:aws:sts::123456789012:assumed-role/Role/arn-user@company.com"
        )

        with patch.object(index, "resolve_quota_for_user") as mock_resolve, \
             patch.object(index, "get_unblock_status", return_value=None), \
             patch.object(index, "get_user_usage_summary", return_value={}):
            mock_resolve.return_value = {
                "monthly_limit": 225000000,
                "daily_limit": 0,
                "enforcement_mode": "alert",
                "enabled": True,
                "warning_threshold_80": 180000000,
                "warning_threshold_90": 202500000,
            }

            result = index.lambda_handler(event, None)
            body = json.loads(result["body"])

            # JWT email takes priority
            mock_resolve.assert_called_once_with("jwt-user@company.com", [])
