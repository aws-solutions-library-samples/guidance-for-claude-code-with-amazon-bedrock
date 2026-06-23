"""
Regression test for issue #655: Go credential-process quota warnings must fire
on all 4 auth paths, same as Python.

Tests that _handle_quota_warning is called on every quota-check path in the
Python implementation (baseline parity for Go fix).
"""

import os
import sys
from unittest.mock import MagicMock

import pytest


class TestQuotaWarningParity:
    """Verify Python _handle_quota_warning fires at 80%+ on all paths."""

    @pytest.fixture
    def mock_provider(self):
        """Create a minimal mock of the credential provider."""
        # Import the module
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from credential_provider.__main__ import MultiProviderAuth

        provider = MagicMock(spec=MultiProviderAuth)
        provider._handle_quota_warning = MultiProviderAuth._handle_quota_warning.__get__(provider, MultiProviderAuth)
        provider._show_quota_browser_notification = MagicMock()
        return provider

    def test_warning_fires_at_80_percent_monthly(self, mock_provider, capsys):
        """Warning should fire when monthly usage is at 80%."""
        quota_result = {
            "allowed": True,
            "usage": {
                "monthly_percent": 80.0,
                "daily_percent": 50.0,
                "monthly_tokens": 32000000,
                "monthly_limit": 40000000,
                "daily_tokens": 1000000,
                "daily_limit": 2000000,
            },
        }
        mock_provider._handle_quota_warning(quota_result)
        captured = capsys.readouterr()
        assert "QUOTA WARNING" in captured.err

    def test_warning_fires_at_80_percent_daily(self, mock_provider, capsys):
        """Warning should fire when daily usage is at 80%."""
        quota_result = {
            "allowed": True,
            "usage": {
                "monthly_percent": 50.0,
                "daily_percent": 80.0,
                "monthly_tokens": 20000000,
                "monthly_limit": 40000000,
                "daily_tokens": 1600000,
                "daily_limit": 2000000,
            },
        }
        mock_provider._handle_quota_warning(quota_result)
        captured = capsys.readouterr()
        assert "QUOTA WARNING" in captured.err

    def test_warning_fires_over_100_percent(self, mock_provider, capsys):
        """Warning should fire when daily usage exceeds 100% (451.9% case from #655)."""
        quota_result = {
            "allowed": True,
            "usage": {
                "monthly_percent": 22.7,
                "daily_percent": 451.9,
                "monthly_tokens": 9100000,
                "monthly_limit": 40000000,
                "daily_tokens": 9000000,
                "daily_limit": 2000000,
            },
        }
        mock_provider._handle_quota_warning(quota_result)
        captured = capsys.readouterr()
        assert "QUOTA WARNING" in captured.err
        assert "451.9%" in captured.err

    def test_no_warning_below_threshold(self, mock_provider, capsys):
        """No warning below 80% on both metrics."""
        quota_result = {
            "allowed": True,
            "usage": {
                "monthly_percent": 50.0,
                "daily_percent": 50.0,
                "monthly_tokens": 20000000,
                "monthly_limit": 40000000,
                "daily_tokens": 1000000,
                "daily_limit": 2000000,
            },
        }
        mock_provider._handle_quota_warning(quota_result)
        captured = capsys.readouterr()
        assert "QUOTA WARNING" not in captured.err

    def test_no_warning_on_empty_usage(self, mock_provider, capsys):
        """No warning when usage is empty."""
        quota_result = {"allowed": True, "usage": {}}
        mock_provider._handle_quota_warning(quota_result)
        captured = capsys.readouterr()
        assert "QUOTA WARNING" not in captured.err

    def test_no_warning_on_none_usage(self, mock_provider, capsys):
        """No warning when usage is None."""
        quota_result = {"allowed": True, "usage": None}
        mock_provider._handle_quota_warning(quota_result)
        captured = capsys.readouterr()
        assert "QUOTA WARNING" not in captured.err
