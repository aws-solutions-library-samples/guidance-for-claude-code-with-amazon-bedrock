# ABOUTME: Lambda function to display count of active users for time range
# ABOUTME: Queries DynamoDB using single-partition schema for real-time accuracy

import json
import boto3
import os
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key

def lambda_handler(event, context):
    if event.get("describe", False):
        return {"markdown": "# Active Users\nUnique users in the time range"}

    region = os.environ["METRICS_REGION"]
    METRICS_TABLE = os.environ.get('METRICS_TABLE', 'ClaudeCodeMetrics')

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(METRICS_TABLE)

    try:
        # Get time range from dashboard
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            # Default to last 24 hours if no time range provided
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=24)).timestamp() * 1000)

        # Convert to datetime and ISO format for queries
        start_dt = datetime.fromtimestamp(start_time / 1000)
        end_dt = datetime.fromtimestamp(end_time / 1000)
        start_iso = start_dt.isoformat() + 'Z'
        end_iso = end_dt.isoformat() + 'Z'
        
        # Query for unique users across the time range
        unique_users = set()
        
        # Single query for all WINDOW summaries in the time range
        response = table.query(
            KeyConditionExpression=Key('pk').eq('METRICS') & 
                                 Key('sk').between(f'{start_iso}#WINDOW#SUMMARY', 
                                                   f'{end_iso}#WINDOW#SUMMARY~'),
            ProjectionExpression='top_users'
        )
        
        # Extract unique users from top_users lists
        for item in response.get('Items', []):
            top_users = item.get('top_users', [])
            for user in top_users:
                if isinstance(user, dict) and 'email' in user:
                    unique_users.add(user['email'])
        
        # Handle pagination if needed
        while 'LastEvaluatedKey' in response:
            response = table.query(
                KeyConditionExpression=Key('pk').eq('METRICS') & 
                                     Key('sk').between(f'{start_iso}#WINDOW#SUMMARY', 
                                                       f'{end_iso}#WINDOW#SUMMARY~'),
                ProjectionExpression='top_users',
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            
            for item in response.get('Items', []):
                top_users = item.get('top_users', [])
                for user in top_users:
                    if isinstance(user, dict) and 'email' in user:
                        unique_users.add(user['email'])
        
        active_users_count = len(unique_users)
        print(f"Total unique users in range: {active_users_count}")
        
        # Build the widget display
        return f"""
        <div style="
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
            border-radius: 8px;
            padding: 10px;
            box-sizing: border-box;
            overflow: hidden;
        ">
            <div style="
                font-size: 30px;
                font-weight: 700;
                color: white;
                text-shadow: 0 2px 4px rgba(0,0,0,0.2);
                margin-bottom: 4px;
                line-height: 1;
            ">{active_users_count}</div>
            <div style="
                font-size: 12px;
                color: rgba(255,255,255,0.9);
                text-transform: uppercase;
                letter-spacing: 0.5px;
                font-weight: 500;
                line-height: 1;
            ">Active Users</div>
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