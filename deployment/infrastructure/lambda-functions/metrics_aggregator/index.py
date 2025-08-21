# ABOUTME: Lambda function that aggregates Claude Code logs into CloudWatch Metrics
# ABOUTME: Runs every 5 minutes to pre-compute metrics for dashboard performance

import json
import boto3
import os
from datetime import datetime, timedelta
import time
from collections import defaultdict
from decimal import Decimal

# Initialize clients
logs_client = boto3.client('logs')
cloudwatch_client = boto3.client('cloudwatch')
dynamodb = boto3.resource('dynamodb')

# Configuration
NAMESPACE = 'ClaudeCode'
LOG_GROUP = os.environ.get('METRICS_LOG_GROUP', '/aws/lambda/bedrock-claude-logs')
METRICS_TABLE = os.environ.get('METRICS_TABLE', 'ClaudeCodeMetrics')
AGGREGATION_WINDOW = 5  # minutes

# DynamoDB table
table = dynamodb.Table(METRICS_TABLE)

def lambda_handler(event, context):
    """
    Aggregate logs from the last 5 minutes and publish to CloudWatch Metrics.
    """
    print(f"Starting metrics aggregation for log group: {LOG_GROUP}")
    
    # Calculate time window
    end_time = datetime.now()
    start_time = end_time - timedelta(minutes=AGGREGATION_WINDOW)
    
    # Convert to milliseconds for CloudWatch Logs
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    
    try:
        # Collect all metrics
        metrics_to_publish = []
        
        # 1. Total Tokens
        total_tokens = aggregate_total_tokens(start_ms, end_ms)
        if total_tokens is not None:
            metrics_to_publish.append({
                'MetricName': 'TotalTokens',
                'Value': total_tokens,
                'Unit': 'Count',
                'Timestamp': end_time
            })
        
        # 2. Active Users (now returns count and details)
        active_users_count, user_details = aggregate_active_users(start_ms, end_ms)
        if active_users_count is not None:
            metrics_to_publish.append({
                'MetricName': 'ActiveUsers',
                'Value': active_users_count,
                'Unit': 'Count',
                'Timestamp': end_time
            })
        
        # Write to DynamoDB
        write_to_dynamodb(end_time, total_tokens, active_users_count, user_details)
        
        # 3. Tokens and Requests by Model
        model_metrics = aggregate_model_metrics(start_ms, end_ms)
        for metric in model_metrics:
            metrics_to_publish.append(metric)
        
        # 4. Cache Metrics
        cache_metrics = aggregate_cache_metrics(start_ms, end_ms)
        for metric in cache_metrics:
            metrics_to_publish.append(metric)
        
        # 5. Top Users
        top_user_metrics = aggregate_top_users(start_ms, end_ms)
        for metric in top_user_metrics:
            metrics_to_publish.append(metric)
        
        # 6. Operations by Type
        operation_metrics = aggregate_operations(start_ms, end_ms)
        for metric in operation_metrics:
            metrics_to_publish.append(metric)
        
        # 7. Code Generation by Language
        language_metrics = aggregate_code_languages(start_ms, end_ms)
        for metric in language_metrics:
            metrics_to_publish.append(metric)
        
        # 8. Commits
        commit_count = aggregate_commits(start_ms, end_ms)
        if commit_count is not None:
            metrics_to_publish.append({
                'MetricName': 'Commits',
                'Value': commit_count,
                'Unit': 'Count',
                'Timestamp': end_time
            })
        
        # Publish metrics in batches (max 20 per request)
        for i in range(0, len(metrics_to_publish), 20):
            batch = metrics_to_publish[i:i+20]
            cloudwatch_client.put_metric_data(
                Namespace=NAMESPACE,
                MetricData=batch
            )
            print(f"Published {len(batch)} metrics to CloudWatch")
        
        print(f"Successfully aggregated and published {len(metrics_to_publish)} metrics")
        return {
            'statusCode': 200,
            'body': json.dumps(f'Published {len(metrics_to_publish)} metrics')
        }
        
    except Exception as e:
        print(f"Error during aggregation: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error: {str(e)}')
        }


def run_query(query, start_ms, end_ms):
    """
    Run a CloudWatch Logs Insights query and wait for results.
    """
    try:
        response = logs_client.start_query(
            logGroupName=LOG_GROUP,
            startTime=start_ms,
            endTime=end_ms,
            queryString=query
        )
        
        query_id = response['queryId']
        
        # Wait for query to complete (max 30 seconds)
        for _ in range(30):
            response = logs_client.get_query_results(queryId=query_id)
            status = response['status']
            
            if status == 'Complete':
                return response.get('results', [])
            elif status in ['Failed', 'Cancelled']:
                print(f"Query failed with status: {status}")
                return []
            
            time.sleep(1)
        
        print("Query timed out")
        return []
        
    except Exception as e:
        print(f"Error running query: {str(e)}")
        return []


def aggregate_total_tokens(start_ms, end_ms):
    """
    Aggregate total token usage.
    """
    query = """
    fields @message
    | filter @message like /claude_code.token.usage/
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | stats sum(tokens) as total_tokens
    """
    
    results = run_query(query, start_ms, end_ms)
    if results and len(results) > 0:
        for field in results[0]:
            if field['field'] == 'total_tokens':
                return float(field['value'])
    return 0


def aggregate_active_users(start_ms, end_ms):
    """
    Count distinct active users and return user details.
    """
    # First get unique count for CloudWatch metric
    query_count = """
    fields @message
    | filter @message like /user.email/
    | parse @message /"user.email":"(?<user>[^"]*)"/
    | stats count_distinct(user) as active_users
    """
    
    unique_count = 0
    results = run_query(query_count, start_ms, end_ms)
    if results and len(results) > 0:
        for field in results[0]:
            if field['field'] == 'active_users':
                unique_count = int(float(field['value']))
    
    # Now get user details for DynamoDB
    query_details = """
    fields @message
    | filter @message like /user.email/
    | parse @message /"user.email":"(?<user>[^"]*)"/
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | stats sum(tokens) as total_tokens, count() as requests by user
    | sort total_tokens desc
    """
    
    user_details = []
    results = run_query(query_details, start_ms, end_ms)
    for result in results:
        user_email = None
        tokens = 0
        requests = 0
        for field in result:
            if field['field'] == 'user':
                user_email = field['value']
            elif field['field'] == 'total_tokens':
                tokens = float(field['value'])
            elif field['field'] == 'requests':
                requests = int(float(field['value']))
        
        if user_email:
            user_details.append({
                'email': user_email,
                'tokens': Decimal(str(tokens)),
                'requests': Decimal(str(requests))
            })
    
    return unique_count, user_details


def aggregate_model_metrics(start_ms, end_ms):
    """
    Aggregate tokens and requests by model.
    """
    metrics = []
    timestamp = datetime.now()
    
    # Tokens by model
    query_tokens = """
    fields @message
    | filter @message like /claude_code.token.usage/
    | parse @message /"model":"(?<model>[^"]*)"/
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | stats sum(tokens) as total_tokens by model
    """
    
    results = run_query(query_tokens, start_ms, end_ms)
    for result in results:
        model = None
        tokens = 0
        for field in result:
            if field['field'] == 'model':
                model = field['value']
            elif field['field'] == 'total_tokens':
                tokens = float(field['value'])
        
        if model and tokens > 0:
            metrics.append({
                'MetricName': 'TokensPerMinute',
                'Dimensions': [{'Name': 'Model', 'Value': model}],
                'Value': tokens / AGGREGATION_WINDOW,  # Convert to per-minute rate
                'Unit': 'Count',
                'Timestamp': timestamp
            })
    
    # Requests by model
    query_requests = """
    fields @message
    | filter @message like /type":"input/
    | parse @message /"model":"(?<model>[^"]*)"/
    | stats count() as requests by model
    """
    
    results = run_query(query_requests, start_ms, end_ms)
    for result in results:
        model = None
        requests = 0
        for field in result:
            if field['field'] == 'model':
                model = field['value']
            elif field['field'] == 'requests':
                requests = float(field['value'])
        
        if model and requests > 0:
            metrics.append({
                'MetricName': 'RequestsPerMinute',
                'Dimensions': [{'Name': 'Model', 'Value': model}],
                'Value': requests / AGGREGATION_WINDOW,  # Convert to per-minute rate
                'Unit': 'Count',
                'Timestamp': timestamp
            })
    
    return metrics


def aggregate_cache_metrics(start_ms, end_ms):
    """
    Aggregate cache hit/miss metrics.
    """
    metrics = []
    timestamp = datetime.now()
    
    query = """
    fields @message
    | filter @message like /claude_code.token.usage/
    | parse @message /"type":"(?<cache_type>[^"]*)"/
    | filter cache_type in ["cacheRead", "cacheCreation"]
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | stats sum(tokens) as total by cache_type
    """
    
    results = run_query(query, start_ms, end_ms)
    cache_reads = 0
    cache_creations = 0
    
    for result in results:
        cache_type = None
        total = 0
        for field in result:
            if field['field'] == 'cache_type':
                cache_type = field['value']
            elif field['field'] == 'total':
                total = float(field['value'])
        
        if cache_type == 'cacheRead':
            cache_reads = total
        elif cache_type == 'cacheCreation':
            cache_creations = total
    
    if cache_reads > 0:
        metrics.append({
            'MetricName': 'CacheHits',
            'Value': cache_reads,
            'Unit': 'Count',
            'Timestamp': timestamp
        })
    
    if cache_creations > 0:
        metrics.append({
            'MetricName': 'CacheMisses',
            'Value': cache_creations,
            'Unit': 'Count',
            'Timestamp': timestamp
        })
    
    # Calculate and store efficiency
    total_cache = cache_reads + cache_creations
    if total_cache > 0:
        efficiency = (cache_reads / total_cache) * 100
        metrics.append({
            'MetricName': 'CacheEfficiency',
            'Value': efficiency,
            'Unit': 'Percent',
            'Timestamp': timestamp
        })
    
    return metrics


def aggregate_top_users(start_ms, end_ms):
    """
    Aggregate top 10 users by token usage.
    """
    metrics = []
    timestamp = datetime.now()
    
    query = """
    fields @message
    | filter @message like /user.email/
    | parse @message /"user.email":"(?<user>[^"]*)"/
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | stats sum(tokens) as total_tokens by user
    | sort total_tokens desc
    | limit 10
    """
    
    results = run_query(query, start_ms, end_ms)
    
    for rank, result in enumerate(results, 1):
        user = None
        tokens = 0
        for field in result:
            if field['field'] == 'user':
                user = field['value']
            elif field['field'] == 'total_tokens':
                tokens = float(field['value'])
        
        if user and tokens > 0:
            # Store as ranked metric
            metrics.append({
                'MetricName': 'TopUserTokens',
                'Dimensions': [
                    {'Name': 'Rank', 'Value': str(rank)},
                    {'Name': 'User', 'Value': user}
                ],
                'Value': tokens,
                'Unit': 'Count',
                'Timestamp': timestamp
            })
    
    return metrics


def aggregate_operations(start_ms, end_ms):
    """
    Aggregate operations by type.
    """
    metrics = []
    timestamp = datetime.now()
    
    query = """
    fields @message
    | filter @message like /tool_name/
    | parse @message /"tool_name":"(?<tool>[^"]*)"/
    | stats count() as usage by tool
    """
    
    results = run_query(query, start_ms, end_ms)
    
    for result in results:
        tool = None
        usage = 0
        for field in result:
            if field['field'] == 'tool':
                tool = field['value']
            elif field['field'] == 'usage':
                usage = float(field['value'])
        
        if tool and usage > 0:
            metrics.append({
                'MetricName': 'OperationCount',
                'Dimensions': [{'Name': 'OperationType', 'Value': tool}],
                'Value': usage,
                'Unit': 'Count',
                'Timestamp': timestamp
            })
    
    return metrics


def aggregate_code_languages(start_ms, end_ms):
    """
    Aggregate code generation by language.
    """
    metrics = []
    timestamp = datetime.now()
    
    query = """
    fields @message
    | filter @message like /code_edit_tool.decision/
    | parse @message /"language":"(?<lang>[^"]*)"/
    | stats count() as edits by lang
    """
    
    results = run_query(query, start_ms, end_ms)
    
    for result in results:
        lang = None
        edits = 0
        for field in result:
            if field['field'] == 'lang':
                lang = field['value']
            elif field['field'] == 'edits':
                edits = float(field['value'])
        
        if lang and edits > 0:
            metrics.append({
                'MetricName': 'CodeEditsByLanguage',
                'Dimensions': [{'Name': 'Language', 'Value': lang}],
                'Value': edits,
                'Unit': 'Count',
                'Timestamp': timestamp
            })
    
    return metrics


def aggregate_commits(start_ms, end_ms):
    """
    Aggregate commit count.
    """
    query = """
    fields @message
    | filter @message like /claude_code.commit.count/
    | stats count() as total_commits
    """
    
    results = run_query(query, start_ms, end_ms)
    if results and len(results) > 0:
        for field in results[0]:
            if field['field'] == 'total_commits':
                return int(float(field['value']))
    return 0


def write_to_dynamodb(timestamp, total_tokens, unique_users, user_details):
    """
    Write aggregated metrics to DynamoDB for improved querying.
    """
    try:
        # Format timestamp for DynamoDB
        ts_str = timestamp.strftime('%Y-%m-%dT%H:%M:%S')
        date_str = timestamp.strftime('%Y-%m-%d')
        ttl = int((timestamp + timedelta(days=30)).timestamp())  # 30 day retention
        
        # Write window summary
        window_item = {
            'pk': f'WINDOW#{ts_str}',
            'sk': 'SUMMARY',
            'timestamp': ts_str,
            'unique_users': unique_users,
            'total_tokens': Decimal(str(total_tokens)) if total_tokens else Decimal(0),
            'top_users': user_details[:10] if user_details else [],  # Top 10 users
            'ttl': ttl
        }
        table.put_item(Item=window_item)
        print(f"Wrote window summary to DynamoDB: {unique_users} users, {total_tokens} tokens")
        
        # Write individual user activity records
        with table.batch_writer() as batch:
            for user in user_details:
                user_item = {
                    'pk': f'USER#{user["email"]}#{date_str}',
                    'sk': f'TS#{timestamp.strftime("%H:%M:%S")}',
                    'timestamp': ts_str,
                    'tokens': Decimal(str(user['tokens'])),
                    'requests': Decimal(str(user['requests'])),
                    'ttl': ttl
                }
                batch.put_item(Item=user_item)
        
        print(f"Wrote {len(user_details)} user records to DynamoDB")
        
        # Update daily aggregate
        daily_key = {
            'pk': f'DAILY#{date_str}',
            'sk': 'USERS'
        }
        
        try:
            # Get existing daily record
            response = table.get_item(Key=daily_key)
            existing_users = set(response.get('Item', {}).get('unique_users', []))
            
            # Add new users
            for user in user_details:
                existing_users.add(user['email'])
            
            # Update daily record
            table.put_item(Item={
                **daily_key,
                'unique_users': list(existing_users),
                'count': len(existing_users),
                'ttl': ttl
            })
            print(f"Updated daily aggregate: {len(existing_users)} unique users")
        except Exception as e:
            print(f"Error updating daily aggregate: {str(e)}")
            
    except Exception as e:
        print(f"Error writing to DynamoDB: {str(e)}")
        # Don't fail the entire aggregation if DynamoDB write fails
        pass