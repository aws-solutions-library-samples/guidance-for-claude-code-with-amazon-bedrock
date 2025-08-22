# ABOUTME: Lambda function to display top users by token usage
# ABOUTME: Queries DynamoDB using single-partition schema for accurate time filtering

import json
import boto3
import os
from datetime import datetime, timedelta
from decimal import Decimal
from boto3.dynamodb.conditions import Key
from collections import defaultdict


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
        return {"markdown": "# Top Users\nTop users by token consumption"}

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
        # Get time range from dashboard
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            # Fallback if no time range provided
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)

        # Convert to datetime and ISO format
        start_dt = datetime.fromtimestamp(start_time / 1000)
        end_dt = datetime.fromtimestamp(end_time / 1000)
        start_iso = start_dt.isoformat() + 'Z'
        end_iso = end_dt.isoformat() + 'Z'
        
        # Aggregate tokens by user across entire time range
        user_tokens = defaultdict(float)
        
        # Single query for all USER records in the time range
        response = table.query(
            KeyConditionExpression=Key('pk').eq('METRICS') & 
                                 Key('sk').between(f'{start_iso}#USER#', 
                                                   f'{end_iso}#USER#~')
        )
        
        # Aggregate tokens by user
        for item in response.get('Items', []):
            # Extract user email from sort key
            # SK format is: ISO_TIMESTAMP#USER#email
            sk_parts = item.get('sk', '').split('#')
            if len(sk_parts) >= 3 and sk_parts[1] == 'USER':
                user_email = '#'.join(sk_parts[2:])  # Handle emails with # if any
                tokens = float(item.get('tokens', Decimal(0)))
                user_tokens[user_email] += tokens
        
        # Handle pagination if needed
        while 'LastEvaluatedKey' in response:
            response = table.query(
                KeyConditionExpression=Key('pk').eq('METRICS') & 
                                     Key('sk').between(f'{start_iso}#USER#', 
                                                       f'{end_iso}#USER#~'),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            
            for item in response.get('Items', []):
                sk_parts = item.get('sk', '').split('#')
                if len(sk_parts) >= 3 and sk_parts[1] == 'USER':
                    user_email = '#'.join(sk_parts[2:])
                    tokens = float(item.get('tokens', Decimal(0)))
                    user_tokens[user_email] += tokens
        
        # Sort users by total tokens and take top 10
        sorted_users = sorted(user_tokens.items(), key=lambda x: x[1], reverse=True)[:10]
        
        users = []
        for user_email, total in sorted_users:
            if total > 0:
                users.append({
                    'user': user_email,
                    'tokens': total
                })
        
        # Calculate total tokens for percentage
        total_all_users = sum(u['tokens'] for u in users)
        
        # Build the display
        items_html = ""
        for i, user in enumerate(users):
            percentage = (user['tokens'] / total_all_users * 100) if total_all_users > 0 else 0
            # Format the username
            username = user['user'].split('@')[0][:20]  # First part of email, truncated
            
            items_html += f"""
            <div style="
                display: flex;
                align-items: center;
                width: 100%;
                height: 24px;
                margin-bottom: 8px;
                font-family: 'Amazon Ember', -apple-system, sans-serif;
            ">
                <div style="
                    width: 120px;
                    padding-right: 12px;
                    font-size: 12px;
                    font-weight: 600;
                    color: #374151;
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    flex-shrink: 0;
                ">{username}</div>
                <div style="
                    flex: 1;
                    position: relative;
                    height: 20px;
                    background: #f3f4f6;
                    border-radius: 4px;
                    overflow: hidden;
                ">
                    <div style="
                        width: {percentage}%;
                        height: 100%;
                        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
                        transition: width 0.3s ease;
                    "></div>
                </div>
                <div style="
                    padding-left: 12px;
                    font-size: 11px;
                    font-weight: 600;
                    color: #374151;
                    text-align: right;
                    min-width: 120px;
                    flex-shrink: 0;
                ">{percentage:.1f}% • {format_number(user['tokens'])}</div>
            </div>
            """
        
        # If no users found
        if not users:
            items_html = """
            <div style="
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100%;
                color: #9ca3af;
                font-size: 14px;
            ">
                No user data available for this time range
            </div>
            """
        
        return f"""
        <div style="
            padding: 16px;
            height: 100%;
            background: white;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            border-radius: 8px;
            box-sizing: border-box;
            overflow-y: auto;
        ">
            {items_html}
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
            padding: 20px;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
        ">
            <div style="text-align: center;">
                <div style="color: #991b1b; font-weight: 600; margin-bottom: 8px; font-size: 14px;">Error Loading Top Users</div>
                <div style="color: #7f1d1d; font-size: 12px;">{error_msg[:100]}</div>
            </div>
        </div>
        """