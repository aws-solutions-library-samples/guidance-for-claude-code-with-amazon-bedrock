import json
import boto3
import os
from datetime import datetime, timedelta
import time
import sys
sys.path.append('/opt')
from query_utils import rate_limited_start_query, wait_for_query_results, validate_time_range
try:
    from metrics_utils import get_metric_statistics, check_metrics_available
except ImportError:
    # Metrics utils not available, will fall back to logs
    pass

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
    if event.get('describe', False):
        return {"markdown": "# Total Tokens Used\nDisplays formatted total token usage"}
    log_group = os.environ['METRICS_LOG_GROUP']
    region = os.environ['METRICS_REGION']
    METRICS_ONLY = os.environ.get('METRICS_ONLY', 'false').lower() == 'true'

    widget_context = event.get('widgetContext', {})
    time_range = widget_context.get('timeRange', {})
    widget_size = widget_context.get('size', {})
    width = widget_size.get('width', 300)
    height = widget_size.get('height', 200)

    logs_client = boto3.client('logs', region_name=region)
    cloudwatch_client = boto3.client('cloudwatch', region_name=region)
    
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
                    print("Using CloudWatch Metrics for total tokens")
                else:
                    print("CloudWatch Metrics not available, falling back to logs")
        except:
            print("Metrics utils not available, using logs")

    try:
        # Always use dashboard time range
        if 'start' in time_range and 'end' in time_range:
            start_time = time_range['start']
            end_time = time_range['end']
        else:
            # Fallback if no time range provided
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)

        # Validate time range (max 7 days)


        is_valid, range_days, error_html = validate_time_range(start_time, end_time)


        if not is_valid:


            return error_html


        
        total_tokens = None
        
        # Try to get data from metrics first
        if use_metrics:
            try:
                print("Fetching total tokens from CloudWatch Metrics")
                datapoints = get_metric_statistics(
                    cloudwatch_client,
                    'TotalTokens',
                    start_time,
                    end_time,
                    None,  # No dimensions for total
                    'Sum',
                    300  # 5-minute periods
                )
                
                if datapoints:
                    # Sum all datapoints for the total
                    total_tokens = sum(point.get('Sum', 0) for point in datapoints)
                    print(f"Retrieved total tokens from metrics: {total_tokens}")
                elif METRICS_ONLY:
                    # In metrics-only mode, don't fall back
                    print("No metrics data available in METRICS_ONLY mode")
                    total_tokens = 0
                else:
                    print("No total tokens data in metrics, falling back to logs")
                    use_metrics = False  # Fall back to logs
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
                    print(f"Error getting total tokens from metrics: {str(e)}")
                    use_metrics = False  # Fall back to logs
        
        # Fall back to logs if metrics not available or failed (and not in METRICS_ONLY mode)
        if not use_metrics and not METRICS_ONLY:
            query = """
            fields @message
            | filter @message like /claude_code.token.usage/
            | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
            | stats sum(tokens) as total_tokens
            """

            response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query
            )

            query_id = response['queryId']
            
            # Wait for results with optimized polling
            response = wait_for_query_results(logs_client, query_id)

            query_status = response.get('status', 'Unknown')

            if query_status == 'Complete':
                if response.get('results') and len(response['results']) > 0:
                    for field in response['results'][0]:
                        if field['field'] == 'total_tokens':
                            total_tokens = float(field['value'])
                            break
                else:
                    total_tokens = 0
            elif query_status == 'Failed':
                raise Exception(f"Query failed: {response.get('statusReason', 'Unknown reason')}")
            elif query_status == 'Cancelled':
                raise Exception("Query was cancelled")
            else:
                raise Exception(f"Query did not complete: {query_status}")

        if total_tokens is None:
            formatted_tokens = "N/A"
        else:
            formatted_tokens = format_number(total_tokens)

        font_size = min(width // 10, height // 5, 48)

        if total_tokens == 0:
            bg_gradient = "linear-gradient(135deg, #6b7280 0%, #4b5563 100%)"
            subtitle = "No Token Usage"
        else:
            bg_gradient = "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
            subtitle = "Total Tokens Used"

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
            ">{formatted_tokens}</div>
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
