# ABOUTME: Unit tests for quota_policies.py — token formatting, parsing, policy CRUD
# ABOUTME: Covers QuotaPolicyManager methods with mocked DynamoDB

"""Tests for claude_code_with_bedrock.quota_policies module."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from claude_code_with_bedrock.quota_policies import (
    PolicyAlreadyExistsError,
    PolicyNotFoundError,
    QuotaPolicyError,
    QuotaPolicyManager,
    _format_tokens,
    _parse_tokens,
)


class TestFormatTokens:
    """Tests for _format_tokens helper."""

    def test_billions(self):
        assert _format_tokens(1_000_000_000) == "1B"

    def test_billions_fractional(self):
        assert _format_tokens(1_500_000_000) == "1.5B"

    def test_millions(self):
        assert _format_tokens(300_000_000) == "300M"

    def test_millions_fractional(self):
        assert _format_tokens(2_500_000) == "2.5M"

    def test_thousands(self):
        assert _format_tokens(50_000) == "50K"

    def test_thousands_fractional(self):
        assert _format_tokens(1_500) == "1.5K"

    def test_small_number(self):
        assert _format_tokens(999) == "999"

    def test_zero(self):
        assert _format_tokens(0) == "0"


class TestParseTokens:
    """Tests for _parse_tokens helper."""

    def test_integer_passthrough(self):
        assert _parse_tokens(300_000_000) == 300_000_000

    def test_billions_suffix(self):
        assert _parse_tokens("1.5B") == 1_500_000_000

    def test_millions_suffix(self):
        assert _parse_tokens("300M") == 300_000_000

    def test_thousands_suffix(self):
        assert _parse_tokens("50K") == 50_000

    def test_lowercase_suffix(self):
        assert _parse_tokens("300m") == 300_000_000

    def test_plain_number_string(self):
        assert _parse_tokens("1000000") == 1_000_000

    def test_whitespace_stripped(self):
        assert _parse_tokens("  300M  ") == 300_000_000

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_tokens("not-a-number")


class TestQuotaPolicyManagerMakePk:
    """Tests for _make_pk key generation."""

    @patch("claude_code_with_bedrock.quota_policies.boto3")
    def test_user_policy_key(self, mock_boto3):
        from claude_code_with_bedrock.models import PolicyType

        manager = QuotaPolicyManager("test-table", region="us-east-1")
        pk = manager._make_pk(PolicyType.USER, "alice@example.com")
        assert pk == "POLICY#user#alice@example.com"

    @patch("claude_code_with_bedrock.quota_policies.boto3")
    def test_group_policy_key(self, mock_boto3):
        from claude_code_with_bedrock.models import PolicyType

        manager = QuotaPolicyManager("test-table", region="us-east-1")
        pk = manager._make_pk(PolicyType.GROUP, "engineering")
        assert pk == "POLICY#group#engineering"

    @patch("claude_code_with_bedrock.quota_policies.boto3")
    def test_default_policy_key(self, mock_boto3):
        from claude_code_with_bedrock.models import PolicyType

        manager = QuotaPolicyManager("test-table", region="us-east-1")
        pk = manager._make_pk(PolicyType.DEFAULT, "default")
        assert pk == "POLICY#default#default"


class TestQuotaPolicyManagerCreatePolicy:
    """Tests for create_policy method."""

    @patch("claude_code_with_bedrock.quota_policies.boto3")
    def test_create_policy_success(self, mock_boto3):
        from claude_code_with_bedrock.models import EnforcementMode, PolicyType

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        manager = QuotaPolicyManager("test-table", region="us-east-1")
        policy = manager.create_policy(
            policy_type=PolicyType.USER,
            identifier="alice@example.com",
            monthly_token_limit=300_000_000,
        )

        assert policy.identifier == "alice@example.com"
        assert policy.monthly_token_limit == 300_000_000
        assert policy.warning_threshold_80 == 240_000_000
        assert policy.warning_threshold_90 == 270_000_000
        mock_table.put_item.assert_called_once()

    @patch("claude_code_with_bedrock.quota_policies.boto3")
    def test_create_policy_already_exists(self, mock_boto3):
        from claude_code_with_bedrock.models import PolicyType

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.put_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
            "PutItem",
        )

        manager = QuotaPolicyManager("test-table", region="us-east-1")
        with pytest.raises(PolicyAlreadyExistsError):
            manager.create_policy(
                policy_type=PolicyType.USER,
                identifier="alice@example.com",
                monthly_token_limit=300_000_000,
            )

    @patch("claude_code_with_bedrock.quota_policies.boto3")
    def test_default_policy_forces_identifier(self, mock_boto3):
        from claude_code_with_bedrock.models import PolicyType

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        manager = QuotaPolicyManager("test-table", region="us-east-1")
        policy = manager.create_policy(
            policy_type=PolicyType.DEFAULT,
            identifier="anything",  # Should be overridden to "default"
            monthly_token_limit=100_000_000,
        )

        assert policy.identifier == "default"

    @patch("claude_code_with_bedrock.quota_policies.boto3")
    def test_auto_calculate_thresholds(self, mock_boto3):
        from claude_code_with_bedrock.models import PolicyType

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        manager = QuotaPolicyManager("test-table", region="us-east-1")
        policy = manager.create_policy(
            policy_type=PolicyType.USER,
            identifier="bob@example.com",
            monthly_token_limit=1_000_000_000,
        )

        assert policy.warning_threshold_80 == 800_000_000
        assert policy.warning_threshold_90 == 900_000_000


class TestQuotaPolicyManagerGetPolicy:
    """Tests for get_policy method."""

    @patch("claude_code_with_bedrock.quota_policies.boto3")
    def test_get_existing_policy(self, mock_boto3):
        from claude_code_with_bedrock.models import PolicyType

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.get_item.return_value = {
            "Item": {
                "pk": "POLICY#user#alice@example.com",
                "sk": "CURRENT",
                "policy_type": "user",
                "identifier": "alice@example.com",
                "monthly_token_limit": 300_000_000,
                "daily_token_limit": None,
                "warning_threshold_80": 240_000_000,
                "warning_threshold_90": 270_000_000,
                "enforcement_mode": "alert",
                "enabled": True,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        }

        manager = QuotaPolicyManager("test-table", region="us-east-1")
        policy = manager.get_policy(PolicyType.USER, "alice@example.com")
        assert policy is not None
        assert policy.monthly_token_limit == 300_000_000

    @patch("claude_code_with_bedrock.quota_policies.boto3")
    def test_get_nonexistent_policy(self, mock_boto3):
        from claude_code_with_bedrock.models import PolicyType

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.get_item.return_value = {}  # No Item key

        manager = QuotaPolicyManager("test-table", region="us-east-1")
        policy = manager.get_policy(PolicyType.USER, "ghost@example.com")
        assert policy is None
