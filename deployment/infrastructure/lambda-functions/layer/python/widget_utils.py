# ABOUTME: Shared utilities for dashboard widget context and configuration
# ABOUTME: Provides consistent time range parsing and widget context handling

from datetime import datetime, timedelta


def parse_widget_context(event):
    """Extract and parse widget context from event."""
    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})
    widget_size = widget_context.get("size", {})
    
    return {
        'time_range': time_range,
        'width': widget_size.get("width", 400),
        'height': widget_size.get("height", 300)
    }


def get_time_range(time_range_dict, default_hours=24):
    """
    Extract and validate time range from widget context.
    Returns start_time, end_time in milliseconds.
    """
    if "start" in time_range_dict and "end" in time_range_dict:
        start_time = time_range_dict["start"]
        end_time = time_range_dict["end"]
    else:
        # Default to specified hours
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(hours=default_hours)).timestamp() * 1000)
    
    return start_time, end_time


def get_time_range_with_dt(time_range_dict, default_hours=24):
    """
    Extract time range and return both milliseconds and datetime objects.
    Returns (start_ms, end_ms, start_dt, end_dt)
    """
    start_ms, end_ms = get_time_range(time_range_dict, default_hours)
    
    start_dt = datetime.fromtimestamp(start_ms / 1000)
    end_dt = datetime.fromtimestamp(end_ms / 1000)
    
    return start_ms, end_ms, start_dt, end_dt


def get_time_range_iso(time_range_dict, default_hours=24):
    """
    Extract time range and return ISO format strings for DynamoDB queries.
    Returns (start_iso, end_iso)
    """
    start_ms, end_ms, start_dt, end_dt = get_time_range_with_dt(time_range_dict, default_hours)
    
    start_iso = start_dt.isoformat() + 'Z'
    end_iso = end_dt.isoformat() + 'Z'
    
    return start_iso, end_iso


def calculate_time_bucket_size(start_dt, end_dt):
    """
    Calculate appropriate time bucket size based on time range.
    Returns bucket size in minutes.
    """
    time_range_hours = (end_dt - start_dt).total_seconds() / 3600
    
    if time_range_hours <= 1:
        return 5  # 5-minute buckets for up to 1 hour
    elif time_range_hours <= 6:
        return 15  # 15-minute buckets for up to 6 hours
    elif time_range_hours <= 24:
        return 60  # 1-hour buckets for up to 24 hours
    elif time_range_hours <= 168:  # 7 days
        return 360  # 6-hour buckets for up to 7 days
    else:
        return 1440  # 1-day buckets for longer ranges


def check_describe_mode(event):
    """Check if widget is in describe mode (returning markdown description)."""
    return event.get("describe", False)