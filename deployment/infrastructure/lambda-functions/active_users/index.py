# ABOUTME: Lambda function to display count of active users for time range
# ABOUTME: Queries DynamoDB using single-partition schema for real-time accuracy

import json
import boto3
import os
import sys
from boto3.dynamodb.conditions import Key
sys.path.append('/opt')
from widget_utils import parse_widget_context, get_time_range_iso, check_describe_mode
from html_utils import generate_error_html, generate_metric_card

def lambda_handler(event, context):
    if check_describe_mode(event):
        return {"markdown": "# Active Users\nUnique users in the time range"}

    region = os.environ["METRICS_REGION"]
    METRICS_TABLE = os.environ.get('METRICS_TABLE', 'ClaudeCodeMetrics')

    widget_ctx = parse_widget_context(event)
    time_range = widget_ctx['time_range']

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(METRICS_TABLE)

    try:
        # Get time range in ISO format for DynamoDB queries
        start_iso, end_iso = get_time_range_iso(time_range, default_hours=24)
        
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
        
        # Build the widget display using shared utility
        return generate_metric_card(
            value=str(active_users_count),
            label="Active Users",
            color="#f59e0b"  # Orange
        )

    except Exception as e:
        return generate_error_html(str(e))