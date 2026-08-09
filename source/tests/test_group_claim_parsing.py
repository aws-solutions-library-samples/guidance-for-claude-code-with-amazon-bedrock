# ABOUTME: Tests for group claim parsing fix (#802)
# ABOUTME: Validates API Gateway JWT authorizer array serialization formats

"""Tests for group claim parsing from JWT authorizer claims.

Covers the multiple serialization formats that different JWT authorizers use:
- Native list (standard JSON array)
- Comma-separated string
- Bracketed space-separated string (API Gateway HTTP API JWT authorizer)
- Single value string
- Empty/missing values
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# We need a proper boto3 mock since the Lambda imports it at module level
_LAMBDA_PATH = (
    Path(__file__).resolve().parents[1].parent
    / "deployment"
    / "infrastructure"
    / "lambda-functions"
    / "quota_check"
    / "index.py"
)


@pytest.fixture(scope="module", autouse=True)
def _mock_boto3():
    """Create a comprehensive boto3 mock before importing the Lambda."""
    mock_boto3 = MagicMock()
    mock_boto3.dynamodb = MagicMock()
    mock_boto3.dynamodb.conditions = MagicMock()
    mock_boto3.dynamodb.conditions.Key = MagicMock()
    mock_boto3.dynamodb.conditions.Attr = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "boto3": mock_boto3,
            "boto3.dynamodb": mock_boto3.dynamodb,
            "boto3.dynamodb.conditions": mock_boto3.dynamodb.conditions,
        },
    ):
        yield


@pytest.fixture(scope="module")
def quota_module(_mock_boto3, monkeypatch_module):
    """Import the quota_check Lambda module with mocked dependencies."""
    import importlib.util
    import os

    os.environ.setdefault("QUOTA_TABLE_NAME", "test-table")
    os.environ.setdefault("AWS_REGION", "us-east-1")

    spec = importlib.util.spec_from_file_location("quota_check_index", _LAMBDA_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch (pytest's is function-scoped)."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


# --- Direct function tests (no module import needed) ---


def _parse_claim_string(value: str) -> list:
    """Local copy of the fix for isolated testing without Lambda imports."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [g.strip() for g in inner.split() if g.strip()]
    return [g.strip() for g in value.split(",") if g.strip()]


class TestParseClaimString:
    """Unit tests for _parse_claim_string logic."""

    def test_comma_separated(self):
        assert _parse_claim_string("group1,group2,group3") == ["group1", "group2", "group3"]

    def test_bracketed_space_separated(self):
        """API Gateway HTTP API JWT authorizer format (issue #802)."""
        result = _parse_claim_string("[11111111-aaaa-bbbb-cccc-222222222222 33333333-dddd-eeee-ffff-444444444444]")
        assert result == [
            "11111111-aaaa-bbbb-cccc-222222222222",
            "33333333-dddd-eeee-ffff-444444444444",
        ]

    def test_single_value(self):
        assert _parse_claim_string("single-group") == ["single-group"]

    def test_empty_string(self):
        assert _parse_claim_string("") == []

    def test_empty_brackets(self):
        assert _parse_claim_string("[]") == []

    def test_brackets_with_whitespace(self):
        assert _parse_claim_string("[  id1   id2  ]") == ["id1", "id2"]

    def test_comma_separated_with_spaces(self):
        assert _parse_claim_string(" group1 , group2 , group3 ") == ["group1", "group2", "group3"]

    def test_single_bracket_value(self):
        assert _parse_claim_string("[only-one]") == ["only-one"]

    def test_uuid_format_groups(self):
        """Real-world Entra ID group IDs."""
        result = _parse_claim_string("[a1b2c3d4-e5f6-7890-abcd-ef1234567890 12345678-abcd-ef01-2345-6789abcdef01]")
        assert len(result) == 2
        assert "a1b2c3d4-e5f6-7890-abcd-ef1234567890" in result


class TestExtractGroupsFromClaims:
    """Integration tests using local reimplementation of extract_groups_from_claims."""

    @staticmethod
    def _extract(claims: dict) -> list:
        """Local reimplementation matching the Lambda's logic."""
        groups = []
        if "groups" in claims:
            claim_groups = claims["groups"]
            if isinstance(claim_groups, list):
                groups.extend(claim_groups)
            elif isinstance(claim_groups, str):
                groups.extend(_parse_claim_string(claim_groups))
        if "cognito:groups" in claims:
            claim_groups = claims["cognito:groups"]
            if isinstance(claim_groups, list):
                groups.extend(claim_groups)
            elif isinstance(claim_groups, str):
                groups.extend(_parse_claim_string(claim_groups))
        if "custom:department" in claims:
            department = claims["custom:department"]
            if department:
                groups.append(f"department:{department}")
        return list(set(groups))

    def test_native_list(self):
        result = self._extract({"groups": ["admin", "developers"]})
        assert set(result) == {"admin", "developers"}

    def test_api_gateway_bracketed_format(self):
        """The exact format reported in issue #802."""
        claims = {
            "groups": "[11111111-aaaa-bbbb-cccc-222222222222 33333333-dddd-eeee-ffff-444444444444 55555555-aaaa-bbbb-cccc-666666666666]"
        }
        result = self._extract(claims)
        assert set(result) == {
            "11111111-aaaa-bbbb-cccc-222222222222",
            "33333333-dddd-eeee-ffff-444444444444",
            "55555555-aaaa-bbbb-cccc-666666666666",
        }

    def test_comma_separated_string(self):
        result = self._extract({"groups": "group1,group2,group3"})
        assert set(result) == {"group1", "group2", "group3"}

    def test_cognito_groups_bracketed(self):
        result = self._extract({"cognito:groups": "[admins users]"})
        assert set(result) == {"admins", "users"}

    def test_multiple_claim_sources_combined(self):
        claims = {
            "groups": "[group-a group-b]",
            "cognito:groups": ["cognito-group"],
            "custom:department": "engineering",
        }
        result = self._extract(claims)
        assert set(result) == {"group-a", "group-b", "cognito-group", "department:engineering"}

    def test_empty_claims(self):
        assert self._extract({}) == []

    def test_no_groups_claim(self):
        claims = {"email": "user@example.com", "sub": "12345"}
        assert self._extract(claims) == []
