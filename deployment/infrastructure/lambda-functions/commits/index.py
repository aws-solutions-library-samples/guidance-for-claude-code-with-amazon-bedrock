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
        return {"markdown": "# Commits\nShows commit activity by user"}

    log_group = os.environ["METRICS_LOG_GROUP"]
    region = os.environ["METRICS_REGION"]

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})

    logs_client = boto3.client("logs", region_name=region)

    try:
        # Always use dashboard time range
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            # Fallback if no time range provided
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)

        # Query for commits by user
        # Validate time range (max 7 days)

        is_valid, range_days, error_html = validate_time_range(start_time, end_time)

        if not is_valid:

            return error_html

        

        query = """
        fields @message
        | filter @message like /claude_code.commit.count/
        | parse @message /"user.email":"(?<user>[^"]*)"/
        | stats count() as commits by user
        | sort commits desc
        | limit 5
        """

        response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query,
        )

        query_id = response['queryId']
        
        # Wait for results with optimized polling
        response = wait_for_query_results(logs_client, query_id)

        query_status = response.get("status", "Unknown")
        commit_data = []

        if query_status == "Complete":
            if response.get("results") and len(response["results"]) > 0:
                for result in response["results"]:
                    user = ""
                    commits = 0
                    for field in result:
                        if field["field"] == "user":
                            user = field["value"]
                        elif field["field"] == "commits":
                            commits = int(float(field["value"]))
                    
                    if user and commits:
                        username = user.split("@")[0]  # Extract username from email
                        commit_data.append({"user": username, "commits": commits})
        elif query_status == "Failed":
            raise Exception(
                f"Query failed: {response.get('statusReason', 'Unknown reason')}"
            )
        elif query_status == "Cancelled":
            raise Exception("Query was cancelled")
        elif query_status in ["Running", "Scheduled"]:
            raise Exception(f"Query timed out: {query_status}")

        # If no user-specific data, try to get total commits
        if not commit_data:
            query2 = """
            fields @message
            | filter @message like /claude_code.commit.count/
            | stats count() as total_commits
            """
            
            response2 = rate_limited_start_query(logs_client, log_group, start_time, end_time, query2,
            )
            
            query_id2 = response2["queryId"]
            time.sleep(1.0)
            
            response2 = wait_for_query_results(logs_client, query_id2)
            if response2.get("status") == "Complete" and response2.get("results"):
                for field in response2["results"][0]:
                    if field["field"] == "total_commits":
                        total = int(float(field["value"]))
                        commit_data.append({"user": "All Users", "commits": total})
                        break

        if not commit_data:
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
                padding: 15px;
                box-sizing: border-box;
                overflow: hidden;
            ">
                <div style="color: white; font-size: 14px; font-weight: 600;">No Commits</div>
                <div style="color: rgba(255,255,255,0.8); font-size: 11px; margin-top: 6px; text-align: center;">No commit data available</div>
            </div>
            """

        # Calculate totals and percentages
        total_commits = sum(item["commits"] for item in commit_data)
        max_commits = max(item["commits"] for item in commit_data)
        
        colors = ["#667eea", "#764ba2", "#f59e0b", "#10b981", "#ef4444"]
        
        bars_html = ""
        for i, item in enumerate(commit_data):
            percentage = (item["commits"] / total_commits * 100) if total_commits > 0 else 0
            bar_width = (item["commits"] / max_commits * 100) if max_commits > 0 else 0
            color = colors[i % len(colors)]
            
            bars_html += f"""
            <div style="
                display: flex;
                align-items: center;
                width: 100%;
                height: 24px;
                margin-bottom: 6px;
                font-family: 'Amazon Ember', -apple-system, sans-serif;
            ">
                <div style="
                    width: 100px;
                    padding-right: 8px;
                    font-size: 11px;
                    font-weight: 600;
                    color: #374151;
                    text-align: right;
                    flex-shrink: 0;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                ">{item['user']}</div>
                <div style="
                    flex: 1;
                    position: relative;
                    height: 20px;
                    background: #f3f4f6;
                    border-radius: 3px;
                    overflow: hidden;
                ">
                    <div style="
                        width: {bar_width}%;
                        height: 100%;
                        background: {color};
                        transition: width 0.3s ease;
                    "></div>
                </div>
                <div style="
                    width: 80px;
                    padding-left: 8px;
                    font-size: 10px;
                    font-weight: 600;
                    color: #374151;
                    text-align: left;
                    flex-shrink: 0;
                ">{item['commits']} ({percentage:.0f}%)</div>
            </div>
            """

        # Add total if we have multiple users
        if len(commit_data) > 1:
            bars_html += f"""
            <div style="
                margin-top: 12px;
                padding-top: 12px;
                border-top: 1px solid #e5e7eb;
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <div style="
                    font-size: 12px;
                    font-weight: 600;
                    color: #374151;
                ">Total Commits</div>
                <div style="
                    font-size: 14px;
                    font-weight: 700;
                    color: #111827;
                ">{total_commits}</div>
            </div>
            """

        return f"""
        <div style="
            padding: 10px;
            height: 100%;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            background: white;
            border-radius: 8px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            justify-content: center;
        ">
            {bars_html}
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