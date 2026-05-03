# ABOUTME: Tests for anonymous/identity mode in OTEL helper
# ABOUTME: Validates _parse_arn_identity(), create_anonymous_user_info(), and get_aws_caller_identity()

import hashlib
import time
from unittest.mock import MagicMock, patch

import sys
import os

# Add source directory to path so we can import otel_helper
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestParseArnIdentity:
    """Tests for _parse_arn_identity() — ARN-based identity extraction"""

    def test_sso_arn_with_email_session(self):
        """AWS SSO assumed-role ARN with email as session name"""
        from otel_helper.__main__ import _parse_arn_identity

        arn = "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_DeveloperAccess_abc123def456/daniel.wirjo@company.com"
        result = _parse_arn_identity(arn)

        assert result is not None
        assert result["username"] == "daniel.wirjo@company.com"
        assert result["email"] == "daniel.wirjo@company.com"
        assert result["role"] == "DeveloperAccess"
        assert result["issuer"] == "aws-sso"

    def test_sso_arn_with_plain_username_session(self):
        """AWS SSO ARN where session name is a plain username (no @)"""
        from otel_helper.__main__ import _parse_arn_identity

        arn = "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_AdminAccess_aabbccdd1234/jsmith"
        result = _parse_arn_identity(arn)

        assert result is not None
        assert result["username"] == "jsmith"
        assert result["email"] == "jsmith@anonymous"  # No @ in session → synthetic email
        assert result["role"] == "AdminAccess"
        assert result["issuer"] == "aws-sso"

    def test_sso_arn_permission_set_with_underscores(self):
        """SSO permission set name containing underscores"""
        from otel_helper.__main__ import _parse_arn_identity

        arn = "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_My_Custom_Set_aabb1122ccdd/user@corp.com"
        result = _parse_arn_identity(arn)

        assert result is not None
        assert result["role"] == "My_Custom_Set"
        assert result["username"] == "user@corp.com"

    def test_iam_user_arn(self):
        """Regular IAM user ARN"""
        from otel_helper.__main__ import _parse_arn_identity

        arn = "arn:aws:iam::123456789012:user/daniel.wirjo"
        result = _parse_arn_identity(arn)

        assert result is not None
        assert result["username"] == "daniel.wirjo"
        assert result["email"] == "daniel.wirjo@anonymous"
        assert result["role"] == "iam-user"
        assert result["issuer"] == "aws-iam"

    def test_iam_user_with_path(self):
        """IAM user ARN with path prefix"""
        from otel_helper.__main__ import _parse_arn_identity

        arn = "arn:aws:iam::123456789012:user/engineering/team-a/jdoe"
        result = _parse_arn_identity(arn)

        assert result is not None
        assert result["username"] == "jdoe"
        assert result["role"] == "iam-user"

    def test_non_sso_assumed_role_returns_none(self):
        """Non-SSO assumed role — identity cannot be determined"""
        from otel_helper.__main__ import _parse_arn_identity

        arn = "arn:aws:sts::123456789012:assumed-role/BedrockDeveloperRole/session-12345"
        result = _parse_arn_identity(arn)

        assert result is None

    def test_none_arn(self):
        """None input returns None"""
        from otel_helper.__main__ import _parse_arn_identity

        assert _parse_arn_identity(None) is None

    def test_empty_arn(self):
        """Empty string returns None"""
        from otel_helper.__main__ import _parse_arn_identity

        assert _parse_arn_identity("") is None

    def test_malformed_arn(self):
        """Malformed ARN returns None"""
        from otel_helper.__main__ import _parse_arn_identity

        assert _parse_arn_identity("not-an-arn") is None
        assert _parse_arn_identity("arn:aws:sts::123") is None

    def test_federated_user_returns_none(self):
        """Federated user ARN — not handled, returns None"""
        from otel_helper.__main__ import _parse_arn_identity

        arn = "arn:aws:sts::123456789012:federated-user/bob"
        result = _parse_arn_identity(arn)

        assert result is None

    def test_sso_arn_without_session_name(self):
        """SSO role ARN with no session name (edge case)"""
        from otel_helper.__main__ import _parse_arn_identity

        # This shouldn't happen in practice, but guard against it
        arn = "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_ReadOnly_aabb1122ccdd"
        result = _parse_arn_identity(arn)

        # No slash after role name → can't extract session
        assert result is None


class TestCreateAnonymousUserInfo:
    """Tests for create_anonymous_user_info() function"""

    def test_sso_identity_extracted(self):
        """SSO caller identity → real username/email, username as user_id"""
        from otel_helper.__main__ import create_anonymous_user_info

        caller_identity = {
            "Arn": "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_DeveloperAccess_abc123def456/alice@corp.com",
            "Account": "123456789012",
            "UserId": "AROAEXAMPLE:alice@corp.com",
        }

        result = create_anonymous_user_info(caller_identity)

        assert result["email"] == "alice@corp.com"
        assert result["username"] == "alice@corp.com"
        assert result["user_id"] == "alice@corp.com"  # Real identity, not hashed
        assert result["role"] == "DeveloperAccess"
        assert result["issuer"] == "aws-sso"
        assert result["organization_id"] == "aws-123456789012"
        assert result["subject"] == caller_identity["Arn"]

    def test_iam_user_identity_extracted(self):
        """IAM user caller identity → username from ARN, username as user_id"""
        from otel_helper.__main__ import create_anonymous_user_info

        caller_identity = {
            "Arn": "arn:aws:iam::123456789012:user/bob",
            "Account": "123456789012",
            "UserId": "AIDAEXAMPLE",
        }

        result = create_anonymous_user_info(caller_identity)

        assert result["username"] == "bob"
        assert result["user_id"] == "bob"  # Real identity, not hashed
        assert result["email"] == "bob@anonymous"
        assert result["role"] == "iam-user"
        assert result["issuer"] == "aws-iam"

    def test_non_sso_role_tracks_session(self):
        """Non-SSO assumed role → tracks role name and session name"""
        from otel_helper.__main__ import create_anonymous_user_info

        caller_identity = {
            "Arn": "arn:aws:sts::123456789012:assumed-role/GenericRole/session-abc",
            "Account": "123456789012",
            "UserId": "AROAEXAMPLE:session-abc",
        }

        result = create_anonymous_user_info(caller_identity)

        assert result["user_id"] == "session-abc"
        assert result["username"] == "session-abc"
        assert result["role"] == "GenericRole"
        assert result["issuer"] == "aws-iam"
        assert result["email"] == "session-abc@anonymous"

    def test_deterministic_identity(self):
        """Same ARN always produces the same user_id"""
        from otel_helper.__main__ import create_anonymous_user_info

        caller_identity = {
            "Arn": "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_Dev_abc123/user@test.com",
            "Account": "123456789012",
        }

        result1 = create_anonymous_user_info(caller_identity)
        result2 = create_anonymous_user_info(caller_identity)

        assert result1["user_id"] == result2["user_id"]
        assert result1["user_id"] == "user@test.com"

    def test_different_arns_produce_different_ids(self):
        """Different ARNs produce different user IDs"""
        from otel_helper.__main__ import create_anonymous_user_info

        id1 = {"Arn": "arn:aws:sts::111111111111:assumed-role/AWSReservedSSO_Dev_abc/a@x.com", "Account": "111111111111"}
        id2 = {"Arn": "arn:aws:sts::222222222222:assumed-role/AWSReservedSSO_Dev_def/b@x.com", "Account": "222222222222"}

        result1 = create_anonymous_user_info(id1)
        result2 = create_anonymous_user_info(id2)

        assert result1["user_id"] != result2["user_id"]
        assert result1["organization_id"] != result2["organization_id"]

    def test_with_none_caller_identity(self):
        """None caller identity → fully anonymous fallback"""
        from otel_helper.__main__ import create_anonymous_user_info

        result = create_anonymous_user_info(None)

        assert result["user_id"] == "anon-unknown"
        assert result["organization_id"] == "unknown"
        assert result["email"] == "anonymous@example.com"
        assert result["username"] == "anonymous"
        assert result["subject"] == "anon-unknown"

    def test_with_empty_caller_identity(self):
        """Empty dict caller identity → fully anonymous fallback"""
        from otel_helper.__main__ import create_anonymous_user_info

        result = create_anonymous_user_info({})

        assert result["user_id"] == "anon-unknown"
        assert result["organization_id"] == "unknown"

    def test_with_missing_account(self):
        """ARN present but no Account field → org_id defaults to aws-unknown"""
        from otel_helper.__main__ import create_anonymous_user_info

        caller_identity = {"Arn": "arn:aws:sts::123456789012:assumed-role/GenericRole/sess"}
        result = create_anonymous_user_info(caller_identity)

        assert result["user_id"] == "sess"  # Session name tracked
        assert result["organization_id"] == "aws-unknown"

    def test_hash_only_for_unrecognised_arn(self):
        """Only truly unrecognisable ARN formats get hashed anonymous IDs"""
        from otel_helper.__main__ import create_anonymous_user_info

        # Federated user — _parse_arn_identity returns None AND _parse_assumed_role_arn returns None
        caller_identity = {
            "Arn": "arn:aws:sts::123456789012:federated-user/bob",
            "Account": "123456789012",
        }
        result = create_anonymous_user_info(caller_identity)

        assert result["user_id"].startswith("anon-")
        assert result["username"] == "anonymous"

    def test_sso_user_default_fields(self):
        """SSO-identified user gets sensible defaults for unresolvable fields"""
        from otel_helper.__main__ import create_anonymous_user_info

        caller_identity = {
            "Arn": "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_Admin_aabb1122/admin@corp.com",
            "Account": "123456789012",
        }

        result = create_anonymous_user_info(caller_identity)

        # These fields can't be extracted from ARN, should have sensible defaults
        assert result["department"] == "unspecified"
        assert result["team"] == "default-team"
        assert result["cost_center"] == "general"
        assert result["manager"] == "unassigned"
        assert result["location"] == "remote"

    def test_all_required_fields_present(self):
        """All required fields are present in output for every code path"""
        from otel_helper.__main__ import create_anonymous_user_info

        required_fields = [
            "email", "user_id", "username", "organization_id", "department",
            "team", "cost_center", "manager", "location", "role",
            "account_uuid", "issuer", "subject",
        ]

        # Test all three code paths
        test_cases = [
            # SSO
            {"Arn": "arn:aws:sts::123:assumed-role/AWSReservedSSO_X_abc/u@t.com", "Account": "123"},
            # Non-SSO role
            {"Arn": "arn:aws:sts::123:assumed-role/MyRole/session", "Account": "123"},
            # None
            None,
        ]

        for identity in test_cases:
            result = create_anonymous_user_info(identity)
            for field in required_fields:
                assert field in result, f"Missing field '{field}' for identity: {identity}"


class TestGetAwsCallerIdentity:
    """Tests for get_aws_caller_identity() function"""

    @patch("otel_helper.__main__.BOTO3_AVAILABLE", False)
    def test_boto3_not_available(self):
        """Graceful handling when boto3 is not installed"""
        from otel_helper.__main__ import get_aws_caller_identity

        result = get_aws_caller_identity()
        assert result is None

    @patch("otel_helper.__main__.BOTO3_AVAILABLE", True)
    @patch("otel_helper.__main__.boto3")
    def test_successful_identity_retrieval(self, mock_boto3):
        """Successful STS GetCallerIdentity call"""
        from otel_helper import __main__ as otel_main
        from otel_helper.__main__ import get_aws_caller_identity

        otel_main._sts_identity_cache.clear()

        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.get_caller_identity.return_value = {
            "Arn": "arn:aws:iam::123456789012:user/test",
            "Account": "123456789012",
            "UserId": "AIDAEXAMPLE",
        }

        result = get_aws_caller_identity()

        assert result is not None
        assert result["Arn"] == "arn:aws:iam::123456789012:user/test"
        assert result["Account"] == "123456789012"
        mock_boto3.client.assert_called_once_with("sts")

    @patch("otel_helper.__main__.BOTO3_AVAILABLE", True)
    @patch("otel_helper.__main__.boto3")
    def test_sts_failure_returns_none(self, mock_boto3):
        """STS API failure returns None gracefully"""
        from otel_helper import __main__ as otel_main
        from otel_helper.__main__ import get_aws_caller_identity

        otel_main._sts_identity_cache.clear()

        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.get_caller_identity.side_effect = Exception("Access denied")

        result = get_aws_caller_identity()
        assert result is None

    @patch("otel_helper.__main__.BOTO3_AVAILABLE", True)
    @patch("otel_helper.__main__.boto3")
    def test_caching_avoids_repeated_calls(self, mock_boto3):
        """STS result is cached and reused within TTL"""
        from otel_helper import __main__ as otel_main
        from otel_helper.__main__ import get_aws_caller_identity

        otel_main._sts_identity_cache.clear()

        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.get_caller_identity.return_value = {
            "Arn": "arn:aws:iam::123456789012:user/cached",
            "Account": "123456789012",
            "UserId": "AIDACACHED",
        }

        result1 = get_aws_caller_identity()
        result2 = get_aws_caller_identity()

        assert result1 == result2
        assert mock_sts.get_caller_identity.call_count == 1

    @patch("otel_helper.__main__.BOTO3_AVAILABLE", True)
    @patch("otel_helper.__main__.boto3")
    def test_cache_expires_after_ttl(self, mock_boto3):
        """Cache expires and STS is called again after TTL"""
        from otel_helper import __main__ as otel_main
        from otel_helper.__main__ import get_aws_caller_identity

        otel_main._sts_identity_cache.clear()

        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.get_caller_identity.return_value = {
            "Arn": "arn:aws:iam::123456789012:user/ttl-test",
            "Account": "123456789012",
            "UserId": "AIDATTL",
        }

        get_aws_caller_identity()
        assert mock_sts.get_caller_identity.call_count == 1

        # Expire the cache manually
        otel_main._sts_identity_cache["default"]["cached_at"] = time.time() - 600

        get_aws_caller_identity()
        assert mock_sts.get_caller_identity.call_count == 2
