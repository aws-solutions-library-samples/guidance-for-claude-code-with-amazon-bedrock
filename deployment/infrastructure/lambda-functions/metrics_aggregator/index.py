# ABOUTME: Lambda function that aggregates Claude Code logs into CloudWatch Metrics
# ABOUTME: Runs every 5 minutes to pre-compute metrics for dashboard performance

import json
import boto3
import os
from datetime import datetime, timedelta
import time
from collections import defaultdict

# Initialize clients
logs_client = boto3.client('logs')
cloudwatch_client = boto3.client('cloudwatch')

# Configuration
NAMESPACE = 'ClaudeCode'
LOG_GROUP = os.environ.get('METRICS_LOG_GROUP', '/aws/lambda/bedrock-claude-logs')
AGGREGATION_WINDOW = 5  # minutes

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
        
        # 2. Active Users
        active_users = aggregate_active_users(start_ms, end_ms)
        if active_users is not None:
            metrics_to_publish.append({
                'MetricName': 'ActiveUsers',
                'Value': active_users,
                'Unit': 'Count',
                'Timestamp': end_time
            })
        
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
    Count distinct active users.
    """
    query = """
    fields @message
    | filter @message like /user.email/
    | parse @message /"user.email":"(?<user>[^"]*)"/
    | stats count_distinct(user) as active_users
    """
    
    results = run_query(query, start_ms, end_ms)
    if results and len(results) > 0:
        for field in results[0]:
            if field['field'] == 'active_users':
                return int(float(field['value']))
    return 0


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