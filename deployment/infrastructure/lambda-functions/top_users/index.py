import json
import boto3
import os
from datetime import datetime, timedelta
import time
import sys
sys.path.append('/opt')
from query_utils import rate_limited_start_query, wait_for_query_results, validate_time_range


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

    log_group = os.environ["METRICS_LOG_GROUP"]
    region = os.environ["METRICS_REGION"]

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})
    widget_size = widget_context.get("size", {})
    width = widget_size.get("width", 300)
    height = widget_size.get("height", 200)

    logs_client = boto3.client("logs", region_name=region)

    try:
        # Always use dashboard time range
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            # Fallback if no time range provided
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)

        # Validate time range (max 7 days)


        is_valid, range_days, error_html = validate_time_range(start_time, end_time)


        if not is_valid:


            return error_html


        


        query = """
        fields @message
        | filter @message like /user.email/
        | parse @message /"user.email":"(?<user>[^"]*)"/
        | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
        | stats sum(tokens) as total_tokens by user
        | sort total_tokens desc
        | limit 10
        """

        response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query,
        )

        query_id = response['queryId']
        
        # Wait for results with optimized polling
        response = wait_for_query_results(logs_client, query_id)

        query_status = response.get("status", "Unknown")
        users = []

        if query_status == "Complete":
            if response.get("results") and len(response["results"]) > 0:
                for result in response["results"]:
                    user_email = ""
                    tokens = 0
                    for field in result:
                        if field["field"] == "user":
                            user_email = field["value"]
                        elif field["field"] == "total_tokens":
                            tokens = float(field["value"])

                    if user_email and tokens:
                        users.append({"email": user_email, "tokens": tokens})
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

        # Calculate total and percentages
        total_tokens = sum(u["tokens"] for u in users)
        colors = [
            "#667eea",
            "#764ba2",
            "#f59e0b",
            "#10b981",
            "#ef4444",
            "#06b6d4",
            "#ec4899",
            "#8b5cf6",
        ]

        # Build ultra compact bar chart HTML with text on bars
        users_html = ""
        max_tokens = users[0]["tokens"] if users else 1  # For scaling bars
        
        for i, user in enumerate(users[:10]):  # Can fit more with ultra compact design
            percentage = (
                (user["tokens"] / total_tokens * 100) if total_tokens > 0 else 0
            )
            bar_width = (user["tokens"] / max_tokens * 100) if max_tokens > 0 else 0
            username = user["email"].split("@")[0]
            
            users_html += f"""
            <div style="
                display: flex;
                align-items: center;
                width: 100%;
                height: 22px;
                margin-bottom: 5px;
                font-family: 'Amazon Ember', -apple-system, sans-serif;
            ">
                <div style="
                    width: 120px;
                    padding-right: 8px;
                    font-size: 11px;
                    font-weight: 600;
                    color: #374151;
                    text-align: right;
                    flex-shrink: 0;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                ">{username}</div>
                <div style="
                    flex: 1;
                    position: relative;
                    height: 18px;
                    background: #f3f4f6;
                    border-radius: 3px;
                    overflow: hidden;
                ">
                    <div style="
                        width: {bar_width}%;
                        height: 100%;
                        background: {colors[i % len(colors)]};
                        transition: width 0.3s ease;
                    "></div>
                </div>
                <div style="
                    width: 100px;
                    padding-left: 8px;
                    font-size: 10px;
                    font-weight: 600;
                    color: #374151;
                    text-align: left;
                    flex-shrink: 0;
                ">{percentage:.1f}% • {format_number(user['tokens'])}</div>
            </div>
            """

        if not users:
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
                padding: 20px;
            ">
                <div style="color: white; font-size: 16px; font-weight: 600;">No User Data</div>
                <div style="color: rgba(255,255,255,0.8); font-size: 12px; margin-top: 8px;">No token usage data available</div>
            </div>
            """

        return f"""
        <div style="
            padding: 12px;
            height: 100%;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            background: white;
            border-radius: 8px;
            box-sizing: border-box;
            overflow-y: auto;
        ">
            {users_html}
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
            font-family: 'Amazon Ember', -apple-system, sans-serif;
        ">
            <div style="text-align: center;">
                <div style="color: #991b1b; font-weight: 600; margin-bottom: 4px; font-size: 14px;">Data Unavailable</div>
                <div style="color: #7f1d1d; font-size: 10px;">{error_msg[:100]}</div>
            </div>
        </div>
        """
