import json
import boto3
import os
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key
from decimal import Decimal


def lambda_handler(event, context):
    if event.get("describe", False):
        return {"markdown": "# Active Users\nNumber of unique users in time period"}

    region = os.environ["METRICS_REGION"]
    METRICS_TABLE = os.environ.get('METRICS_TABLE', 'ClaudeCodeMetrics')

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})
    widget_size = widget_context.get("size", {})
    width = widget_size.get("width", 300)
    height = widget_size.get("height", 200)

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(METRICS_TABLE)

    try:
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

        # Convert timestamps to datetime
        start_dt = datetime.fromtimestamp(start_time / 1000)
        end_dt = datetime.fromtimestamp(end_time / 1000)
        
        # Query for daily aggregates in the time range
        unique_users = set()
        current_date = start_dt.date()
        end_date = end_dt.date()
        
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            try:
                response = table.get_item(
                    Key={
                        'pk': f'DAILY#{date_str}',
                        'sk': 'USERS'
                    }
                )
                if 'Item' in response:
                    daily_users = response['Item'].get('unique_users', [])
                    unique_users.update(daily_users)
                    print(f"Found {len(daily_users)} users for {date_str}")
            except Exception as e:
                print(f"Error querying daily aggregate for {date_str}: {str(e)}")
            
            current_date += timedelta(days=1)
        
        # If no daily data, query window summaries
        if not unique_users:
            print("No daily aggregates found, querying window summaries")
            
            # Query WINDOW records by pk prefix
            response = table.query(
                KeyConditionExpression=Key('pk').begins_with('WINDOW#') & Key('sk').eq('SUMMARY')
            )
            
            for item in response.get('Items', []):
                timestamp = item.get('timestamp', '')
                # Check if timestamp is in range
                if timestamp >= start_dt.strftime('%Y-%m-%dT%H:%M:%S') and timestamp <= end_dt.strftime('%Y-%m-%dT%H:%M:%S'):
                    top_users = item.get('top_users', [])
                    for user in top_users:
                        unique_users.add(user.get('email'))
        
        user_count = len(unique_users)
        print(f"Total unique users: {user_count}")

        # Format display
        if user_count == 0:
            bg_gradient = "linear-gradient(135deg, #6b7280 0%, #4b5563 100%)"
            subtitle = "No Active Users"
        else:
            bg_gradient = "linear-gradient(135deg, #f59e0b 0%, #d97706 100%)"
            subtitle = "Active Users"

        font_size = min(width // 10, height // 5, 48)

        return f"""
        <div style="
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            background: {bg_gradient};
            border-radius: 8px;
            padding: 10px;
            box-sizing: border-box;
            overflow: hidden;
        ">
            <div style="
                font-size: {font_size}px;
                font-weight: 700;
                color: white;
                text-shadow: 0 2px 4px rgba(0,0,0,0.2);
                margin-bottom: 4px;
                line-height: 1;
            ">{user_count}</div>
            <div style="
                font-size: 12px;
                color: rgba(255,255,255,0.9);
                text-transform: uppercase;
                letter-spacing: 0.5px;
                font-weight: 500;
                line-height: 1;
            ">{subtitle}</div>
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
            box-sizing: border-box;
            overflow: hidden;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
        ">
            <div style="text-align: center; width: 100%; overflow: hidden;">
                <div style="color: #991b1b; font-weight: 600; margin-bottom: 4px; font-size: 14px;">Data Unavailable</div>
                <div style="color: #7f1d1d; font-size: 10px;">{error_msg[:100]}</div>
            </div>
        </div>
        """