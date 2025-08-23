# ABOUTME: Shared formatting utilities for dashboard widgets
# ABOUTME: Provides consistent number, time, and data formatting across all widgets

def format_number(num):
    """Format numbers with K, M, B suffixes for display."""
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 10_000:
        return f"{num / 1_000:.0f}K"
    else:
        return f"{num:,.0f}"


def format_compact_number(num):
    """Ultra compact number formatting for tight spaces."""
    if num >= 1_000_000:
        return f"{num/1_000_000:.0f}M"  # No decimal for millions
    elif num >= 10_000:
        return f"{num/1_000:.0f}K"  # No decimal for 10K+
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"  # One decimal for 1-10K
    else:
        return f"{num:.0f}"


def format_percentage(value, total, decimals=1):
    """Calculate and format percentage."""
    if total == 0:
        return "0%"
    percentage = (value / total * 100)
    return f"{percentage:.{decimals}f}%"


def format_timestamp_utc(timestamp_ms):
    """Format timestamp to readable time with UTC indicator."""
    if timestamp_ms is None:
        return ""
    from datetime import datetime
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime("%-I:%M %p UTC")


def format_compact_time(timestamp_ms):
    """Compact time format for tight spaces."""
    if timestamp_ms is None:
        return ""
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return dt.strftime("%-I:%M%p UTC")  # 3:25AM UTC