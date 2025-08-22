# ABOUTME: Lambda function to display lines added/removed over time as a dual-line chart
# ABOUTME: Queries DynamoDB using single-partition schema for line change events

import json
import boto3
import os
from datetime import datetime, timedelta
from decimal import Decimal
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

        # Convert to datetime and ISO format
        start_dt = datetime.fromtimestamp(start_time / 1000)
        end_dt = datetime.fromtimestamp(end_time / 1000)
        start_iso = start_dt.isoformat() + 'Z'
        end_iso = end_dt.isoformat() + 'Z'

        # Query individual line events instead of aggregated windows
        all_events = []
        
        # Single query for all LINE events in time range
        response = table.query(
            KeyConditionExpression=Key('pk').eq('METRICS') & 
                                 Key('sk').between(f'{start_iso}#LINES#EVENT#', 
                                                   f'{end_iso}#LINES#EVENT#~')
        )
        
        # Collect all events
        for item in response.get('Items', []):
            event_type = item.get('type', '')
            count = float(item.get('count', Decimal(0)))
            timestamp_str = item.get('timestamp', '')
            
            if timestamp_str and event_type and count > 0:
                # Parse the timestamp
                try:
                    event_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    all_events.append({
                        'timestamp': event_dt,
                        'type': event_type,
                        'count': count
                    })
                except:
                    pass
        
        # Handle pagination if needed
        while 'LastEvaluatedKey' in response:
            response = table.query(
                KeyConditionExpression=Key('pk').eq('METRICS') & 
                                     Key('sk').between(f'{start_iso}#LINES#EVENT#', 
                                                       f'{end_iso}#LINES#EVENT#~'),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            
            for item in response.get('Items', []):
                event_type = item.get('type', '')
                count = float(item.get('count', Decimal(0)))
                timestamp_str = item.get('timestamp', '')
                
                if timestamp_str and event_type and count > 0:
                    try:
                        event_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        all_events.append({
                            'timestamp': event_dt,
                            'type': event_type,
                            'count': count
                        })
                    except:
                        pass
        
        # Sort events by timestamp
        all_events.sort(key=lambda x: x['timestamp'])
        
        # Group events into time buckets for visualization
        # Calculate appropriate bucket size based on time range
        time_range_hours = (end_dt - start_dt).total_seconds() / 3600
        
        if time_range_hours <= 1:
            bucket_minutes = 5  # 5-minute buckets for up to 1 hour
        elif time_range_hours <= 6:
            bucket_minutes = 15  # 15-minute buckets for up to 6 hours
        elif time_range_hours <= 24:
            bucket_minutes = 60  # 1-hour buckets for up to 24 hours
        elif time_range_hours <= 168:  # 7 days
            bucket_minutes = 360  # 6-hour buckets for up to 7 days
        else:
            bucket_minutes = 1440  # 1-day buckets for longer ranges
        
        # Create time buckets
        time_series = {}
        
        for event in all_events:
            # Round down to nearest bucket
            bucket_dt = event['timestamp'].replace(second=0, microsecond=0)
            minutes = bucket_dt.minute
            bucket_minutes_rounded = (minutes // bucket_minutes) * bucket_minutes
            bucket_dt = bucket_dt.replace(minute=bucket_minutes_rounded)
            
            bucket_key = bucket_dt.isoformat()
            
            if bucket_key not in time_series:
                time_series[bucket_key] = {"added": 0, "removed": 0}
            
            if event['type'] == 'added':
                time_series[bucket_key]["added"] += event['count']
            elif event['type'] == 'removed':
                time_series[bucket_key]["removed"] += event['count']

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

        # Calculate chart dimensions (leave space for legend on right)
        chart_width = width - 180  # More space for right legend
        chart_height = height - 80
        
        # Find max value for scaling
        max_value = max(
            max(time_series[t].get("added", 0), time_series[t].get("removed", 0)) 
            for t in sorted_times
        )
        if max_value == 0:
            max_value = 100
        
        # Calculate time range for proper X-axis positioning
        start_timestamp = datetime.fromisoformat(sorted_times[0])
        end_timestamp = datetime.fromisoformat(sorted_times[-1])
        time_range_seconds = (end_timestamp - start_timestamp).total_seconds()
        
        # Create SVG paths for both lines
        added_points = []
        removed_points = []
        
        for timestamp in sorted_times:
            # Position based on actual time, not index
            point_time = datetime.fromisoformat(timestamp)
            time_offset = (point_time - start_timestamp).total_seconds()
            x = (time_offset / time_range_seconds) * chart_width if time_range_seconds > 0 else chart_width / 2
            
            added_value = time_series[timestamp].get("added", 0)
            removed_value = time_series[timestamp].get("removed", 0)
            
            added_y = chart_height - (added_value / max_value * chart_height) if max_value > 0 else chart_height
            removed_y = chart_height - (removed_value / max_value * chart_height) if max_value > 0 else chart_height
            
            added_points.append(f"{x},{added_y}")
            removed_points.append(f"{x},{removed_y}")
        
        added_path = "M " + " L ".join(added_points) if added_points else ""
        removed_path = "M " + " L ".join(removed_points) if removed_points else ""
        
        # Generate Y-axis labels (0 to max)
        y_labels = []
        for i in range(5):
            value = int(max_value * (i / 4))
            y_pos = chart_height - (i * chart_height / 4)
            # Only add label if it's not a duplicate
            if i == 0 or value != int(max_value * ((i-1) / 4)):
                y_labels.append(f'<text x="-5" y="{y_pos + 4}" text-anchor="end" fill="#6b7280" font-size="11">{format_number(value)}</text>')
        
        # Generate X-axis labels
        x_labels = []
        label_interval = max(1, len(sorted_times) // 8)
        for i in range(0, len(sorted_times), label_interval):
            # Position based on actual time, not index
            label_time = datetime.fromisoformat(sorted_times[i])
            time_offset = (label_time - start_timestamp).total_seconds()
            x = (time_offset / time_range_seconds) * chart_width if time_range_seconds > 0 else chart_width / 2
            time_label = label_time.strftime('%H:%M')
            x_labels.append(
                f'<text x="{x}" y="{chart_height + 15}" text-anchor="middle" fill="#9ca3af" font-size="9">{time_label}</text>'
            )
        
        # Calculate totals from all individual events
        total_added = sum(event['count'] for event in all_events if event['type'] == 'added')
        total_removed = sum(event['count'] for event in all_events if event['type'] == 'removed')
        
        return f"""
        <div style="
            padding: 15px;
            height: 100%;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            background: white;
            border-radius: 8px;
            box-sizing: border-box;
            overflow: hidden;
            display: flex;
            align-items: center;
        ">
            <svg width="{chart_width + 60}" height="{height - 30}" style="overflow: visible;">
                <!-- Grid lines -->
                <g transform="translate(40, 20)">
                    <g stroke="#e5e7eb" stroke-width="0.5">
                        <line x1="0" y1="0" x2="0" y2="{chart_height}" />
                        <line x1="0" y1="{chart_height}" x2="{chart_width}" y2="{chart_height}" />
                        {"".join([f'<line x1="0" y1="{i * chart_height / 4}" x2="{chart_width}" y2="{i * chart_height / 4}" stroke-dasharray="2,2" />' for i in range(1, 4)])}
                    </g>
                    
                    <!-- Lines only, no fill -->
                    <path d="{added_path}" fill="none" stroke="#10b981" stroke-width="2" />
                    <path d="{removed_path}" fill="none" stroke="#ef4444" stroke-width="2" />
                    
                    <!-- Y-axis labels -->
                    {"".join(y_labels)}
                    
                    <!-- X-axis labels -->
                    {"".join(x_labels)}
                </g>
            </svg>
            
            <!-- Legend on the right -->
            <div style="
                margin-left: 20px;
                padding: 10px;
                background: #f9fafb;
                border-radius: 4px;
                min-width: 100px;
            ">
                <div style="font-size: 10px; color: #6b7280; margin-bottom: 8px; font-weight: 600;">LEGEND</div>
                <div style="display: flex; flex-direction: column; gap: 6px;">
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <span style="width: 16px; height: 2px; background: #10b981; display: inline-block;"></span>
                        <span style="font-size: 11px; color: #374151;">Added</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <span style="width: 16px; height: 2px; background: #ef4444; display: inline-block;"></span>
                        <span style="font-size: 11px; color: #374151;">Removed</span>
                    </div>
                </div>
                <div style="margin-top: 12px; padding-top: 8px; border-top: 1px solid #e5e7eb;">
                    <div style="font-size: 10px; color: #6b7280; margin-bottom: 4px;">TOTALS</div>
                    <div style="font-size: 12px; color: #111827;">
                        <div>↑ {format_number(total_added)}</div>
                        <div>↓ {format_number(total_removed)}</div>
                    </div>
                </div>
            </div>
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