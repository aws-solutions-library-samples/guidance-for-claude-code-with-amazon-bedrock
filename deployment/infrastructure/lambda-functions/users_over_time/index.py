# ABOUTME: Lambda function to display active users over time as a line chart
# ABOUTME: Queries DynamoDB using single-partition schema for user activity trends

import json
import boto3
import os
from datetime import datetime, timedelta, date
from boto3.dynamodb.conditions import Key

def lambda_handler(event, context):
    if event.get("describe", False):
        return {"markdown": "# Users Over Time\nActive users timeline"}

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

        print(f"Querying users over time from {start_dt} to {end_dt}")

        # Convert to ISO format for queries
        start_iso = start_dt.isoformat() + 'Z'
        end_iso = end_dt.isoformat() + 'Z'
        
        data_points = []
        
        # Single query for all WINDOW summaries in time range
        response = table.query(
            KeyConditionExpression=Key('pk').eq('METRICS') & 
                                 Key('sk').between(f'{start_iso}#WINDOW#SUMMARY', 
                                                   f'{end_iso}#WINDOW#SUMMARY~'),
            ProjectionExpression='sk, timestamp, unique_users, total_tokens'
        )
        
        # Process results
        for item in response.get('Items', []):
            # Extract timestamp from sort key (ISO format)
            sk_parts = item.get('sk', '').split('#')
            if len(sk_parts) >= 3 and sk_parts[1] == 'WINDOW':
                iso_timestamp = sk_parts[0]
                users = float(item.get('unique_users', 0))
                
                # Parse timestamp
                try:
                    dt = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
                    
                    data_points.append({
                        'timestamp': dt.isoformat(),
                        'time': dt.strftime('%H:%M'),
                        'date': dt.strftime('%Y-%m-%d'),
                        'users': users
                    })
                except:
                    pass
        
        # Handle pagination if needed
        while 'LastEvaluatedKey' in response:
            response = table.query(
                KeyConditionExpression=Key('pk').eq('METRICS') & 
                                     Key('sk').between(f'{start_iso}#WINDOW#SUMMARY', 
                                                       f'{end_iso}#WINDOW#SUMMARY~'),
                ProjectionExpression='sk, timestamp, unique_users, total_tokens',
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            
            for item in response.get('Items', []):
                sk_parts = item.get('sk', '').split('#')
                if len(sk_parts) >= 3 and sk_parts[1] == 'WINDOW':
                    iso_timestamp = sk_parts[0]
                    users = float(item.get('unique_users', 0))
                    
                    try:
                        dt = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
                        
                        data_points.append({
                            'timestamp': dt.isoformat(),
                            'time': dt.strftime('%H:%M'),
                            'date': dt.strftime('%Y-%m-%d'),
                            'users': users
                        })
                    except:
                        pass

        # Sort by timestamp
        data_points.sort(key=lambda x: x['timestamp'])

        if not data_points:
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
                        Waiting for metrics to be collected
                    </div>
                </div>
            </div>
            """

        # Calculate chart dimensions
        chart_width = width - 80
        chart_height = height - 100
        
        # Find max users for scaling
        max_users = max(p['users'] for p in data_points) if data_points else 10
        
        # Create SVG path for line chart
        path_points = []
        for i, point in enumerate(data_points):
            x = (i / (len(data_points) - 1)) * chart_width if len(data_points) > 1 else chart_width / 2
            y = chart_height - (point['users'] / max_users * chart_height) if max_users > 0 else chart_height
            path_points.append(f"{x},{y}")
        
        path = "M " + " L ".join(path_points) if path_points else ""
        
        # Create area path (filled area under line)
        area_path = path + f" L {chart_width},{chart_height} L 0,{chart_height} Z" if path else ""
        
        # Generate Y-axis labels (0 to max, 5 labels total)
        y_labels = []
        for i in range(5):
            value = int(max_users * (i / 4))
            y_pos = chart_height - (i * chart_height / 4)
            # Only add label if it's not a duplicate
            if i == 0 or value != int(max_users * ((i-1) / 4)):
                y_labels.append(f'<text x="-5" y="{y_pos + 4}" text-anchor="end" fill="#6b7280" font-size="11">{value}</text>')
        
        # Generate X-axis labels (show every Nth point to avoid crowding)
        x_labels = []
        label_interval = max(1, len(data_points) // 10)
        for i in range(0, len(data_points), label_interval):
            x = (i / (len(data_points) - 1)) * chart_width if len(data_points) > 1 else chart_width / 2
            x_labels.append(
                f'<text x="{x}" y="{chart_height + 15}" text-anchor="middle" fill="#9ca3af" font-size="9">{data_points[i]["time"]}</text>'
            )
        
        # Create dots for data points (if not too many)
        dots = []
        if len(data_points) <= 50:
            for i, point in enumerate(data_points):
                x = (i / (len(data_points) - 1)) * chart_width if len(data_points) > 1 else chart_width / 2
                y = chart_height - (point['users'] / max_users * chart_height) if max_users > 0 else chart_height
                dots.append(
                    f'<circle cx="{x}" cy="{y}" r="3" fill="#1f77b4" />'
                    f'<title>{point["time"]}: {point["users"]} users</title>'
                )

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
            <div style="margin-bottom: 10px;">
                <span style="font-size: 14px; font-weight: 600; color: #374151;">
                    Active Users: {data_points[-1]['users'] if data_points else 0}
                </span>
                <span style="font-size: 11px; color: #6b7280; margin-left: 10px;">
                    ({len(data_points)} data points)
                </span>
            </div>
            
            <svg width="{width - 40}" height="{height - 60}" style="overflow: visible;">
                <!-- Grid lines -->
                <g stroke="#e5e7eb" stroke-width="0.5">
                    <line x1="0" y1="0" x2="0" y2="{chart_height}" />
                    <line x1="0" y1="{chart_height}" x2="{chart_width}" y2="{chart_height}" />
                    {"".join([f'<line x1="0" y1="{i * chart_height / 4}" x2="{chart_width}" y2="{i * chart_height / 4}" stroke-dasharray="2,2" opacity="0.5" />' for i in range(1, 4)])}
                </g>
                
                <!-- Chart -->
                <g transform="translate(40, 20)">
                    <!-- Area under line -->
                    <path d="{area_path}" fill="url(#gradient)" opacity="0.3" />
                    
                    <!-- Line -->
                    <path d="{path}" fill="none" stroke="#1f77b4" stroke-width="2" />
                    
                    <!-- Data points -->
                    {"".join(dots)}
                    
                    <!-- Y-axis labels -->
                    {"".join(y_labels)}
                    
                    <!-- X-axis labels -->
                    {"".join(x_labels)}
                </g>
                
                <!-- Gradient definition -->
                <defs>
                    <linearGradient id="gradient" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:#1f77b4;stop-opacity:0.8" />
                        <stop offset="100%" style="stop-color:#1f77b4;stop-opacity:0.1" />
                    </linearGradient>
                </defs>
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