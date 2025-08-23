# ABOUTME: Lambda function to display top users by token usage
# ABOUTME: Queries DynamoDB using single-partition schema for accurate time filtering

import json
import boto3
import os
import sys
from decimal import Decimal
from boto3.dynamodb.conditions import Key
from collections import defaultdict
sys.path.append('/opt')
from widget_utils import parse_widget_context, get_time_range_iso, check_describe_mode
from html_utils import generate_error_html
from format_utils import format_number, format_percentage


def lambda_handler(event, context):
    if check_describe_mode(event):
        return {"markdown": "# Top Users\nTop users by token consumption"}

    region = os.environ["METRICS_REGION"]
    METRICS_TABLE = os.environ.get('METRICS_TABLE', 'ClaudeCodeMetrics')

    widget_ctx = parse_widget_context(event)
    width = widget_ctx['width']
    height = widget_ctx['height']
    time_range = widget_ctx['time_range']

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(METRICS_TABLE)

    try:
        # Get time range in ISO format for DynamoDB queries
        start_iso, end_iso = get_time_range_iso(time_range, default_hours=1)
        
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
            percentage_str = format_percentage(user['tokens'], total_all_users)
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
                ">{percentage_str} • {format_number(user['tokens'])}</div>
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
        return generate_error_html(str(e), title="Error Loading Top Users")