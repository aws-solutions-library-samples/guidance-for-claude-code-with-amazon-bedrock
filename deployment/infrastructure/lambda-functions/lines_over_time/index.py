# ABOUTME: Lambda function to display lines added/removed over time as a dual-line chart
# ABOUTME: Shows time series visualization of code changes tracked in CloudWatch Logs

import json
import boto3
import os
from datetime import datetime, timedelta
import time
import sys
sys.path.append('/opt')
from query_utils import rate_limited_start_query, wait_for_query_results, validate_time_range


def format_number(num):
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 10_000:
        return f"{num / 1_000:.0f}K"
    else:
        return f"{num:,.0f}"


def lambda_handler(event, context):
    if event.get("describe", False):
        return {"markdown": "# Lines Over Time\nCode changes timeline"}

    log_group = os.environ["METRICS_LOG_GROUP"]
    region = os.environ["METRICS_REGION"]

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})
    widget_size = widget_context.get("size", {})
    width = widget_size.get("width", 600)
    height = widget_size.get("height", 400)

    logs_client = boto3.client("logs", region_name=region)

    try:
        # Get time range from dashboard
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=24)).timestamp() * 1000)

        # Validate time range
        is_valid, range_days, error_html = validate_time_range(start_time, end_time, max_days=7)
        if not is_valid:
            return error_html

        # Query for lines added/removed over time
        query = """
        fields @timestamp, @message
        | filter @message like /claude_code.lines_of_code.count/
        | parse @message /"type":"(?<type>[^"]*)"/
        | parse @message /"claude_code.lines_of_code.count":(?<lines>[0-9.]+)/
        | stats sum(lines) as total by type, bin(30m) as time_window
        | sort time_window asc
        """

        response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query)
        query_id = response['queryId']
        
        # Wait for results
        response = wait_for_query_results(logs_client, query_id)

        query_status = response.get("status", "Unknown")
        
        if query_status != "Complete":
            raise Exception(f"Query failed with status: {query_status}")

        # Process results into time series
        time_series = {}  # {timestamp: {added: X, removed: Y}}
        
        for result in response.get("results", []):
            time_window = None
            line_type = None
            total = 0
            
            for field in result:
                if field["field"] == "time_window":
                    time_window = field["value"]
                elif field["field"] == "type":
                    line_type = field["value"].lower()
                elif field["field"] == "total":
                    total = float(field["value"])
            
            if time_window and line_type:
                if time_window not in time_series:
                    time_series[time_window] = {"added": 0, "removed": 0}
                time_series[time_window][line_type] = total

        # Sort by timestamp
        sorted_times = sorted(time_series.keys())
        
        if not sorted_times:
            return """
            <div style="
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100%;
                background: linear-gradient(135deg, #6b7280 0%, #4b5563 100%);
                border-radius: 8px;
                padding: 20px;
                font-family: 'Amazon Ember', -apple-system, sans-serif;
            ">
                <div style="text-align: center; color: white;">
                    <div style="font-size: 16px; font-weight: 600;">No Data Available</div>
                    <div style="font-size: 12px; margin-top: 8px; opacity: 0.8;">
                        Waiting for code changes to be tracked
                    </div>
                </div>
            </div>
            """

        # Calculate chart dimensions
        chart_width = width - 80
        chart_height = height - 100
        
        # Find max value for scaling
        max_value = max(
            max(time_series[t].get("added", 0), time_series[t].get("removed", 0)) 
            for t in sorted_times
        )
        if max_value == 0:
            max_value = 100
        
        # Create SVG paths for both lines
        added_points = []
        removed_points = []
        
        for i, timestamp in enumerate(sorted_times):
            x = (i / (len(sorted_times) - 1)) * chart_width if len(sorted_times) > 1 else chart_width / 2
            
            added_value = time_series[timestamp].get("added", 0)
            removed_value = time_series[timestamp].get("removed", 0)
            
            added_y = chart_height - (added_value / max_value * chart_height)
            removed_y = chart_height - (removed_value / max_value * chart_height)
            
            added_points.append(f"{x},{added_y}")
            removed_points.append(f"{x},{removed_y}")
        
        added_path = "M " + " L ".join(added_points) if added_points else ""
        removed_path = "M " + " L ".join(removed_points) if removed_points else ""
        
        # Create area paths (filled areas under lines)
        added_area = added_path + f" L {chart_width},{chart_height} L 0,{chart_height} Z" if added_path else ""
        removed_area = removed_path + f" L {chart_width},{chart_height} L 0,{chart_height} Z" if removed_path else ""
        
        # Generate Y-axis labels
        y_labels = []
        for i in range(5):
            value = int(max_value * (i / 4))
            y_pos = chart_height - (i * chart_height / 4)
            y_labels.append(f'<text x="-5" y="{y_pos + 4}" text-anchor="end" fill="#9ca3af" font-size="10">{format_number(value)}</text>')
        
        # Generate X-axis labels
        x_labels = []
        label_interval = max(1, len(sorted_times) // 8)
        for i in range(0, len(sorted_times), label_interval):
            x = (i / (len(sorted_times) - 1)) * chart_width if len(sorted_times) > 1 else chart_width / 2
            # Parse timestamp and format
            dt = datetime.fromisoformat(sorted_times[i].replace('Z', '+00:00'))
            time_label = dt.strftime('%H:%M')
            x_labels.append(
                f'<text x="{x}" y="{chart_height + 15}" text-anchor="middle" fill="#9ca3af" font-size="9">{time_label}</text>'
            )
        
        # Calculate totals
        total_added = sum(time_series[t].get("added", 0) for t in sorted_times)
        total_removed = sum(time_series[t].get("removed", 0) for t in sorted_times)
        
        return f"""
        <div style="
            padding: 20px;
            height: 100%;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            background: white;
            border-radius: 8px;
            box-sizing: border-box;
        ">
            <div style="margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
                <div style="display: flex; gap: 20px;">
                    <span style="display: flex; align-items: center; gap: 5px;">
                        <span style="width: 12px; height: 3px; background: #10b981; display: inline-block;"></span>
                        <span style="font-size: 11px; color: #374151;">Added: {format_number(total_added)}</span>
                    </span>
                    <span style="display: flex; align-items: center; gap: 5px;">
                        <span style="width: 12px; height: 3px; background: #ef4444; display: inline-block;"></span>
                        <span style="font-size: 11px; color: #374151;">Removed: {format_number(total_removed)}</span>
                    </span>
                </div>
                <span style="font-size: 11px; color: #6b7280;">
                    ({len(sorted_times)} data points)
                </span>
            </div>
            
            <svg width="{width - 40}" height="{height - 60}" style="overflow: visible;">
                <!-- Grid lines -->
                <g stroke="#e5e7eb" stroke-width="0.5">
                    <line x1="0" y1="0" x2="0" y2="{chart_height}" />
                    <line x1="0" y1="{chart_height}" x2="{chart_width}" y2="{chart_height}" />
                    {"".join([f'<line x1="0" y1="{i * chart_height / 4}" x2="{chart_width}" y2="{i * chart_height / 4}" stroke-dasharray="2,2" />' for i in range(1, 4)])}
                </g>
                
                <!-- Chart -->
                <g transform="translate(40, 20)">
                    <!-- Area under lines -->
                    <path d="{added_area}" fill="#10b981" opacity="0.1" />
                    <path d="{removed_area}" fill="#ef4444" opacity="0.1" />
                    
                    <!-- Lines -->
                    <path d="{added_path}" fill="none" stroke="#10b981" stroke-width="2" />
                    <path d="{removed_path}" fill="none" stroke="#ef4444" stroke-width="2" />
                    
                    <!-- Y-axis labels -->
                    {"".join(y_labels)}
                    
                    <!-- X-axis labels -->
                    {"".join(x_labels)}
                </g>
            </svg>
        </div>
        """

    except Exception as e:
        error_msg = str(e)
        return f"""
        <div style="
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            background: #fef2f2;
            border-radius: 8px;
            padding: 10px;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
        ">
            <div style="text-align: center;">
                <div style="color: #991b1b; font-weight: 600; font-size: 14px;">
                    Data Unavailable
                </div>
                <div style="color: #7f1d1d; font-size: 10px; margin-top: 4px;">
                    {error_msg[:100]}
                </div>
            </div>
        </div>
        """