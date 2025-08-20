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
        return {"markdown": "# Active Users\nNumber of unique users in time period"}

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
            start_time = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

        # Validate time range (max 7 days)


        is_valid, range_days, error_html = validate_time_range(start_time, end_time)


        if not is_valid:


            return error_html


        


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

        user_count = None
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
