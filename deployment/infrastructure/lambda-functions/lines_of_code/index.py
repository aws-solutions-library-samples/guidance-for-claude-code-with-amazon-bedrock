# ABOUTME: Lambda function to display count of lines added/removed
# ABOUTME: Queries DynamoDB using single-partition schema for line change events

import json
import boto3
import os
import sys
from decimal import Decimal
from boto3.dynamodb.conditions import Key
sys.path.append('/opt')
from widget_utils import parse_widget_context, get_time_range_iso, check_describe_mode
from html_utils import generate_error_html
from format_utils import format_number


def lambda_handler(event, context):
    if check_describe_mode(event):
        return {"markdown": "# Lines of Code\nShows lines added and removed"}

    region = os.environ["METRICS_REGION"]
    METRICS_TABLE = os.environ.get('METRICS_TABLE', 'ClaudeCodeMetrics')

    widget_ctx = parse_widget_context(event)
    time_range = widget_ctx['time_range']

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(METRICS_TABLE)

    try:
        # Get time range in ISO format for DynamoDB queries
        start_iso, end_iso = get_time_range_iso(time_range, default_hours=7*24)
        
        line_stats = {"added": 0, "removed": 0}
        
        # Single query for all LINE events in time range
        response = table.query(
            KeyConditionExpression=Key('pk').eq('METRICS') & 
                                 Key('sk').between(f'{start_iso}#LINES#EVENT#', 
                                                   f'{end_iso}#LINES#EVENT#~')
        )
        
        # Sum up all events
        for item in response.get('Items', []):
            event_type = item.get('type', '').lower()
            count = float(item.get('count', Decimal(0)))
            
            if event_type == 'added':
                line_stats["added"] += count
            elif event_type == 'removed':
                line_stats["removed"] += count
        
        # Handle pagination if needed
        while 'LastEvaluatedKey' in response:
            response = table.query(
                KeyConditionExpression=Key('pk').eq('METRICS') & 
                                     Key('sk').between(f'{start_iso}#LINES#EVENT#', 
                                                       f'{end_iso}#LINES#EVENT#~'),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            
            for item in response.get('Items', []):
                event_type = item.get('type', '').lower()
                count = float(item.get('count', Decimal(0)))
                
                if event_type == 'added':
                    line_stats["added"] += count
                elif event_type == 'removed':
                    line_stats["removed"] += count

        # Build the display
        items = [
            {"label": "Lines Added", "value": line_stats["added"], "color": "#10b981"},
            {"label": "Lines Removed", "value": line_stats["removed"], "color": "#ef4444"}
        ]
        
        total_lines = line_stats["added"] + line_stats["removed"]
        max_value = max(line_stats["added"], line_stats["removed"], 1)
        
        bars_html = ""
        for item in items:
            percentage = (item["value"] / total_lines * 100) if total_lines > 0 else 0
            bar_width = (item["value"] / max_value * 100) if max_value > 0 else 0
            
            bars_html += f"""
            <div style="
                display: flex;
                align-items: center;
                width: 100%;
                height: 24px;
                margin-bottom: 6px;
                font-family: 'Amazon Ember', -apple-system, sans-serif;
            ">
                <div style="
                    width: 100px;
                    padding-right: 8px;
                    font-size: 11px;
                    font-weight: 600;
                    color: #374151;
                    text-align: right;
                    flex-shrink: 0;
                ">{item['label']}</div>
                <div style="
                    flex: 1;
                    position: relative;
                    height: 20px;
                    background: #f3f4f6;
                    border-radius: 3px;
                    overflow: hidden;
                ">
                    <div style="
                        width: {bar_width}%;
                        height: 100%;
                        background: {item['color']};
                        transition: width 0.3s ease;
                    "></div>
                </div>
                <div style="
                    width: 100px;
                    padding-left: 8px;
                    font-size: 10px;
                    font-weight: 600;
                    color: #374151;
                    text-align: left;
                    flex-shrink: 0;
                ">{format_number(item['value'])}</div>
            </div>
            """

        # Add total summary
        bars_html += f"""
        <div style="
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #e5e7eb;
            display: flex;
            justify-content: space-between;
            align-items: center;
        ">
            <div style="
                font-size: 12px;
                font-weight: 600;
                color: #374151;
            ">Total Changes</div>
            <div style="
                font-size: 14px;
                font-weight: 700;
                color: #111827;
            ">{format_number(total_lines)}</div>
        </div>
        """

        return f"""
        <div style="
            padding: 12px;
            height: 100%;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            background: white;
            border-radius: 8px;
            box-sizing: border-box;
        ">
            {bars_html}
        </div>
        """

    except Exception as e:
        return generate_error_html(str(e))