# ABOUTME: Tests that 'ccwb quota usage' applies the stale-day guard to daily_tokens
# ABOUTME: An idle user's frozen daily counter must display as 0 on a new UTC day

"""Regression tests for QuotaUsageCommand._get_user_usage stale-day reset.

Without the guard, the CLI read daily_tokens verbatim, so an idle user whose
daily_date is from a prior day kept showing a stale over-limit percentage that
never reset — matching what admins saw alongside the repeating alert emails.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from claude_code_with_bedrock.cli.commands.quota import QuotaUsageCommand


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yesterday() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _make_profile():
    profile = MagicMock()
    profile.user_quota_metrics_table = "TestUserQuotaMetrics"
    profile.aws_region = "us-east-1"
    profile.stack_names = {}
    return profile


def _patch_table(item: dict):
    """Return a patch context yielding a boto3.resource whose table returns `item`."""
    table = MagicMock()
    table.get_item.return_value = {"Item": item}
    resource = MagicMock()
    resource.Table.return_value = table
    return patch("boto3.resource", return_value=resource)


@pytest.fixture
def command():
    return QuotaUsageCommand()


def test_stale_day_resets_daily_tokens(command):
    profile = _make_profile()
    item = {
        "total_tokens": 3_355_533,
        "daily_tokens": 3_355_533,  # frozen above limit
        "daily_date": _yesterday(),
    }
    with _patch_table(item):
        usage = command._get_user_usage(profile, "idle.user@example.com")

    assert usage["daily_tokens"] == 0, "stale daily counter must display as 0"
    assert usage["total_tokens"] == 3_355_533, "monthly total must be untouched"
    assert usage["daily_date"] == _yesterday()


def test_same_day_keeps_daily_tokens(command):
    profile = _make_profile()
    item = {
        "total_tokens": 3_355_533,
        "daily_tokens": 3_355_533,
        "daily_date": _today(),
    }
    with _patch_table(item):
        usage = command._get_user_usage(profile, "active.user@example.com")

    assert usage["daily_tokens"] == 3_355_533, "same-day daily usage must be preserved"


def test_missing_daily_date_resets(command):
    """A row without daily_date (legacy) is treated as stale -> 0."""
    profile = _make_profile()
    item = {"total_tokens": 1000, "daily_tokens": 500}
    with _patch_table(item):
        usage = command._get_user_usage(profile, "legacy.user@example.com")

    assert usage["daily_tokens"] == 0
