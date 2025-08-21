import json
import boto3
import os
from datetime import datetime, timedelta
import time
import sys
from boto3.dynamodb.conditions import Key, Attr
sys.path.append('/opt')
from query_utils import rate_limited_start_query, wait_for_query_results, validate_time_range
try:
    from metrics_utils import get_metric_statistics, check_metrics_available
except ImportError:
    # Metrics utils not available, will fall back to logs
    pass


def lambda_handler(event, context):
    if event.get("describe", False):
        return {"markdown": "# Active Users\nNumber of unique users in time period"}

    log_group = os.environ["METRICS_LOG_GROUP"]
    region = os.environ["METRICS_REGION"]
    METRICS_ONLY = os.environ.get('METRICS_ONLY', 'false').lower() == 'true'
    METRICS_TABLE = os.environ.get('METRICS_TABLE', 'ClaudeCodeMetrics')

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})
    widget_size = widget_context.get("size", {})
    width = widget_size.get("width", 300)
    height = widget_size.get("height", 200)

    logs_client = boto3.client("logs", region_name=region)
    cloudwatch_client = boto3.client("cloudwatch", region_name=region)
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(METRICS_TABLE)
    
    # Check if we should use metrics only mode
    if METRICS_ONLY:
        print("METRICS_ONLY mode enabled - using CloudWatch Metrics directly")
        use_metrics = True
    else:
        # Check if metrics are available for fallback mode
        use_metrics = False
        try:
            if 'metrics_utils' in sys.modules:
                use_metrics = check_metrics_available(cloudwatch_client)
                if use_metrics:
                    print("Using CloudWatch Metrics for active users")
                else:
                    print("CloudWatch Metrics not available, falling back to logs")
        except:
            print("Metrics utils not available, using logs")

    try:
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

        # Validate time range (max 7 days)


        is_valid, range_days, error_html = validate_time_range(start_time, end_time)


        if not is_valid:


            return error_html


        
        user_count = None
        
        # Try to get data from DynamoDB first (most accurate)
        try:
            print("Fetching active users from DynamoDB")
            
            # Convert timestamps to datetime for comparison
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
            
            if unique_users:
                user_count = len(unique_users)
                print(f"Retrieved {user_count} unique users from DynamoDB")
            else:
                # Fall back to window summaries if no daily aggregates
                print("No daily aggregates found, querying window summaries")
                
                # Query WINDOW records
                response = table.query(
                    IndexName='TimestampIndex',
                    KeyConditionExpression=Key('timestamp').between(
                        start_dt.strftime('%Y-%m-%dT%H:%M:%S'),
                        end_dt.strftime('%Y-%m-%dT%H:%M:%S')
                    )
                )
                
                # Collect unique users from all windows
                window_users = set()
                for item in response.get('Items', []):
                    if item.get('sk') == 'SUMMARY':
                        top_users = item.get('top_users', [])
                        for user in top_users:
                            window_users.add(user.get('email'))
                
                if window_users:
                    user_count = len(window_users)
                    print(f"Retrieved {user_count} unique users from window summaries")
                
        except Exception as e:
            print(f"Error querying DynamoDB: {str(e)}")
            
            # Fall back to CloudWatch Metrics if DynamoDB fails
            if use_metrics:
                try:
                    print("Falling back to CloudWatch Metrics")
                    datapoints = get_metric_statistics(
                        cloudwatch_client,
                        'ActiveUsers',
                        start_time,
                        end_time,
                        None,
                        'Maximum',
                        300
                    )
                    
                    if datapoints:
                        user_count = int(max(point.get('Maximum', 0) for point in datapoints))
                        print(f"Retrieved active users from metrics: {user_count}")
                    elif METRICS_ONLY:
                        print("No metrics data available in METRICS_ONLY mode")
                        user_count = 0
                    else:
                        print("No active users data in metrics, falling back to logs")
                        use_metrics = False
            except Exception as e:
                if METRICS_ONLY:
                    # In metrics-only mode, return error instead of falling back
                    print(f"Metrics error in METRICS_ONLY mode: {str(e)}")
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
                            <div style="color: #991b1b; font-weight: 600; margin-bottom: 4px; font-size: 14px;">Metrics Unavailable</div>
                            <div style="color: #7f1d1d; font-size: 10px;">{str(e)[:100]}</div>
                            <div style="color: #7f1d1d; font-size: 9px; margin-top: 4px;">METRICS_ONLY mode - no fallback</div>
                        </div>
                    </div>
                    """
                else:
                    print(f"Error getting active users from metrics: {str(e)}")
                    use_metrics = False  # Fall back to logs
        
        # Fall back to logs if metrics not available or failed (and not in METRICS_ONLY mode)
        if not use_metrics and not METRICS_ONLY:
            query = """
            fields @message
            | filter @message like /user.email/
            | parse @message /"user.email":"(?<user>[^"]*)"/
            | stats count_distinct(user) as active_users
            """

            response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query,
            )

            query_id = response['queryId']
            
            # Wait for results with optimized polling
            response = wait_for_query_results(logs_client, query_id)

            query_status = response.get("status", "Unknown")

            if query_status == "Complete":
                if response.get("results") and len(response["results"]) > 0:
                    for field in response["results"][0]:
                        if field["field"] == "active_users":
                            user_count = int(float(field["value"]))
                            break
                else:
                    user_count = 0
            elif query_status == "Failed":
                raise Exception(
                    f"Query failed: {response.get('statusReason', 'Unknown reason')}"
                )
            elif query_status == "Cancelled":
                raise Exception("Query was cancelled")
            else:
                raise Exception(f"Query did not complete: {query_status}")

        if user_count is None:
            formatted_users = "N/A"
        else:
            formatted_users = str(user_count)

        font_size = min(width // 10, height // 5, 48)

        if user_count == 0:
            bg_gradient = "linear-gradient(135deg, #6b7280 0%, #4b5563 100%)"
            subtitle = "No Active Users"
        else:
            bg_gradient = "linear-gradient(135deg, #f59e0b 0%, #d97706 100%)"
            subtitle = "Active Users"

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
            ">{formatted_users}</div>
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
                <div style="color: #7f1d1d; font-size: 10px; word-wrap: break-word; overflow: hidden; text-overflow: ellipsis; max-height: 40px;">{error_msg[:100]}</div>
                <div style="color: #7f1d1d; font-size: 9px; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">Log: {log_group.split('/')[-1]}</div>
            </div>
        </div>
        """
