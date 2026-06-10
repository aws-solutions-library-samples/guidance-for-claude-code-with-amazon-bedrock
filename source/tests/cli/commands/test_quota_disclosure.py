# ABOUTME: Tests for cache read disclosure in quota CLI commands
# ABOUTME: Verifies the disclosure note appears in quota set/show/usage output

"""Tests for quota cache read disclosure feature (#403)."""

from io import StringIO
from unittest.mock import patch

from rich.console import Console

from claude_code_with_bedrock.cli.commands.quota import (
    CACHE_READ_DISCLOSURE,
    _print_cache_read_disclosure,
)


class TestCacheReadDisclosure:
    """Tests for cache read disclosure in quota commands."""

    def test_cache_read_disclosure_constant_exists(self):
        """CACHE_READ_DISCLOSURE constant is defined and non-empty."""
        assert CACHE_READ_DISCLOSURE
        assert "cache reads" in CACHE_READ_DISCLOSURE.lower() or "cache" in CACHE_READ_DISCLOSURE.lower()

    def test_cache_read_disclosure_mentions_multiplier(self):
        """Disclosure mentions the 5x multiplier for 80% cache hit ratio."""
        assert "5x" in CACHE_READ_DISCLOSURE
        assert "80%" in CACHE_READ_DISCLOSURE

    def test_cache_read_disclosure_mentions_formula(self):
        """Disclosure includes the cache hit ratio formula."""
        assert "1 / (1 - cache_hit_ratio)" in CACHE_READ_DISCLOSURE

    def test_cache_read_disclosure_mentions_ratios(self):
        """Disclosure shows cache hit ratio guide with 75%, 80%, 90%."""
        assert "75%" in CACHE_READ_DISCLOSURE
        assert "80%" in CACHE_READ_DISCLOSURE
        assert "90%" in CACHE_READ_DISCLOSURE
        assert "4x" in CACHE_READ_DISCLOSURE
        assert "5x" in CACHE_READ_DISCLOSURE
        assert "10x" in CACHE_READ_DISCLOSURE

    def test_print_cache_read_disclosure_outputs(self):
        """_print_cache_read_disclosure prints to console."""
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        _print_cache_read_disclosure(console)
        rendered = output.getvalue()
        # Rich strips markup, check plain text content
        assert "cache" in rendered.lower()
        assert "5x" in rendered
