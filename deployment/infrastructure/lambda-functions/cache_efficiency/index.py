import json
import boto3
import os
from datetime import datetime, timedelta
import time
import sys
sys.path.append('/opt')
from query_utils import rate_limited_start_query, wait_for_query_results, validate_time_range


def lambda_handler(event, context):
    if event.get("describe", False):
        return {"markdown": "# Cache Efficiency\nCache hit rate percentage"}

    log_group = os.environ["METRICS_LOG_GROUP"]
    region = os.environ["METRICS_REGION"]

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})
    widget_size = widget_context.get("size", {})
    width = widget_size.get("width", 300)
    height = widget_size.get("height", 200)

    logs_client = boto3.client("logs", region_name=region)

    try:
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)

        # Validate time range (max 7 days)


        is_valid, range_days, error_html = validate_time_range(start_time, end_time)


        if not is_valid:


            return error_html


        


        query = """
        fields @message
        | filter @message like /claude_code.token.usage/
        | parse @message /"type":"(?<cache_type>[^"]*)"/
        | filter cache_type in ["cacheRead", "cacheCreation"]
        | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
        | stats sum(tokens) as total by cache_type
        """

        response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query,
        )

        query_id = response['queryId']
        
        # Wait for results with optimized polling
        response = wait_for_query_results(logs_client, query_id)

        query_status = response.get("status", "Unknown")
        cache_reads = 0
        cache_creations = 0

        if query_status == "Complete":
            if response.get("results") and len(response["results"]) > 0:
                for result in response["results"]:
                    cache_type = ""
                    total = 0
                    for field in result:
                        if field["field"] == "cache_type":
                            cache_type = field["value"]
                        elif field["field"] == "total":
                            total = float(field["value"])

                    if cache_type == "cacheRead":
                        cache_reads = total
                    elif cache_type == "cacheCreation":
                        cache_creations = total
            else:
                pass
        elif query_status == "Failed":
            raise Exception(
                f"Query failed: {response.get('statusReason', 'Unknown reason')}"
            )
        elif query_status == "Cancelled":
            raise Exception("Query was cancelled")
        elif query_status in ["Running", "Scheduled"]:
            raise Exception(f"Query timed out: {query_status}")
        else:
            raise Exception(f"Query status: {query_status}")

        total = cache_reads + cache_creations
        efficiency = (cache_reads / total * 100) if total > 0 else None

        font_size = min(width // 10, height // 5, 48)

        if efficiency is None or total == 0:
            return f"""
            <div style="
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: 100%;
                font-family: 'Amazon Ember', -apple-system, sans-serif;
                background: linear-gradient(135deg, #6b7280 0%, #4b5563 100%);
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
                ">N/A</div>
                <div style="
                    font-size: 12px;
                    color: rgba(255,255,255,0.9);
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    font-weight: 500;
                    line-height: 1;
                ">No Cache Data</div>
            </div>
            """

        if efficiency >= 70:
            color = "#10b981"  # Green
            status = "●"
        elif efficiency >= 50:
            color = "#f59e0b"  # Yellow
            status = "◐"
        else:
            color = "#ef4444"  # Red
            status = "○"

        return f"""
        <div style="
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            background: linear-gradient(135deg, {color} 0%, {color}aa 100%);
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
            ">{efficiency:.0f}% {status}</div>
            <div style="
                font-size: 12px;
                color: rgba(255,255,255,0.9);
                text-transform: uppercase;
                letter-spacing: 0.5px;
                font-weight: 500;
                line-height: 1;
            ">Cache Efficiency</div>
            <div style="
                margin-top: 8px;
                font-size: 10px;
                color: rgba(255,255,255,0.8);
                line-height: 1;
            ">{int(cache_reads):,} cached / {int(total):,} tokens</div>
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
