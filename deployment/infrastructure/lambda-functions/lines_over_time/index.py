# ABOUTME: Lambda function to display lines added/removed over time as a dual-line chart
# ABOUTME: Queries DynamoDB for time series data of code changes

import json
import boto3
import os
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key


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

    region = os.environ["METRICS_REGION"]
    METRICS_TABLE = os.environ.get('METRICS_TABLE', 'ClaudeCodeMetrics')

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})
    widget_size = widget_context.get("size", {})
    width = widget_size.get("width", 600)
    height = widget_size.get("height", 400)

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(METRICS_TABLE)

    try:
        # Get time range from dashboard
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=24)).timestamp() * 1000)

        # Convert to datetime
        start_dt = datetime.fromtimestamp(start_time / 1000)
        end_dt = datetime.fromtimestamp(end_time / 1000)

        time_series = {}  # {timestamp: {added: X, removed: Y}}
        
        # Query each day in the range
        current_date = start_dt.date()
        end_date = end_dt.date()
        
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            
            # Determine time boundaries for this day
            if current_date == start_dt.date():
                start_time_str = start_dt.strftime('%H:%M:%S')
            else:
                start_time_str = '00:00:00'
                
            if current_date == end_dt.date():
                end_time_str = end_dt.strftime('%H:%M:%S')
            else:
                end_time_str = '23:59:59'
            
            # Query METRICS for window data which includes lines
            response = table.query(
                KeyConditionExpression=Key('pk').eq(f'METRICS#{date_str}') & 
                                     Key('sk').between(f'{start_time_str}#WINDOW#SUMMARY', 
                                                       f'{end_time_str}#WINDOW#SUMMARY~'),
                ProjectionExpression='sk, lines_added, lines_removed'
            )
            
            # Process results
            for item in response.get('Items', []):
                # Extract time from sort key
                sk_parts = item.get('sk', '').split('#')
                if len(sk_parts) >= 3 and sk_parts[1] == 'WINDOW':
                    time_str = sk_parts[0]
                    
                    # Create full timestamp
                    dt = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M:%S')
                    timestamp_key = dt.isoformat()
                    
                    time_series[timestamp_key] = {
                        "added": float(item.get('lines_added', 0)),
                        "removed": float(item.get('lines_removed', 0))
                    }
            
            # Move to next day
            current_date += timedelta(days=1)

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
            dt = datetime.fromisoformat(sorted_times[i])
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
            overflow: hidden;
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
            
            <svg width="{width - 40}" height="{height - 60}" style="overflow: hidden;">
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
            overflow: hidden;
            box-sizing: border-box;
        ">
            <div style="text-align: center; width: 100%; overflow: hidden;">
                <div style="color: #991b1b; font-weight: 600; font-size: 14px;">
                    Data Unavailable
                </div>
                <div style="color: #7f1d1d; font-size: 10px; margin-top: 4px; word-wrap: break-word; overflow: hidden; text-overflow: ellipsis;">
                    {error_msg[:100]}
                </div>
            </div>
        </div>
        """