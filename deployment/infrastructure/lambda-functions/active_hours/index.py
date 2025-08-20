import json
import boto3
import os
from datetime import datetime, timedelta
import time
import sys
sys.path.append('/opt')
from query_utils import rate_limited_start_query, wait_for_query_results, validate_time_range


def format_hours(hours):
    if hours >= 1000:
        return f"{hours / 1000:.1f}K"
    elif hours >= 100:
        return f"{hours:.0f}"
    else:
        return f"{hours:.1f}"


def lambda_handler(event, context):
    if event.get("describe", False):
        return {"markdown": "# Active Hours\nShows active development time by user"}

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

        # Query for active hours by user
        # Validate time range (max 7 days)

        is_valid, range_days, error_html = validate_time_range(start_time, end_time)

        if not is_valid:

            return error_html

        

        query = """
        fields @message
        | filter @message like /active_time.total/
        | parse @message /"user.email":"(?<user>[^"]*)"/
        | parse @message /"claude_code.active_time.total":(?<time>[0-9.]+)/
        | stats sum(time)/3600 as hours by user
        | sort hours desc
        | limit 5
        """

        response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query,
        )

        query_id = response['queryId']
        
        # Wait for results with optimized polling
        response = wait_for_query_results(logs_client, query_id)

        query_status = response.get("status", "Unknown")
        hours_data = []

        if query_status == "Complete":
            if response.get("results") and len(response["results"]) > 0:
                for result in response["results"]:
                    user = ""
                    hours = 0
                    for field in result:
                        if field["field"] == "user":
                            user = field["value"]
                        elif field["field"] == "hours":
                            hours = float(field["value"])
                    
                    if user and hours:
                        username = user.split("@")[0]  # Extract username from email
                        hours_data.append({"user": username, "hours": hours})
        elif query_status == "Failed":
            raise Exception(
                f"Query failed: {response.get('statusReason', 'Unknown reason')}"
            )
        elif query_status == "Cancelled":
            raise Exception("Query was cancelled")
        elif query_status in ["Running", "Scheduled"]:
            raise Exception(f"Query timed out: {query_status}")

        # If no user-specific data, try to get total hours
        if not hours_data:
            query2 = """
            fields @message
            | filter @message like /active_time.total/
            | parse @message /"claude_code.active_time.total":(?<time>[0-9.]+)/
            | stats sum(time)/3600 as total_hours
            """
            
            response2 = rate_limited_start_query(logs_client, log_group, start_time, end_time, query2,
            )
            
            query_id2 = response2["queryId"]
            time.sleep(1.0)
            
            response2 = wait_for_query_results(logs_client, query_id2)
            if response2.get("status") == "Complete" and response2.get("results"):
                for field in response2["results"][0]:
                    if field["field"] == "total_hours":
                        total = float(field["value"])
                        hours_data.append({"user": "All Users", "hours": total})
                        break

        if not hours_data:
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
                <div style="color: white; font-size: 16px; font-weight: 600;">No Active Hours</div>
                <div style="color: rgba(255,255,255,0.8); font-size: 12px; margin-top: 8px;">No activity data available for this period</div>
            </div>
            """

        # Calculate totals and percentages
        total_hours = sum(item["hours"] for item in hours_data)
        max_hours = max(item["hours"] for item in hours_data)
        
        colors = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444"]
        
        bars_html = ""
        for i, item in enumerate(hours_data):
            percentage = (item["hours"] / total_hours * 100) if total_hours > 0 else 0
            bar_width = (item["hours"] / max_hours * 100) if max_hours > 0 else 0
            color = colors[i % len(colors)]
            
            # Format hours display
            hours_display = format_hours(item["hours"])
            hours_label = "hrs" if item["hours"] != 1 else "hr"
            
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
                    width: 100px;
                    padding-left: 8px;
                    font-size: 10px;
                    font-weight: 600;
                    color: #374151;
                    text-align: left;
                    flex-shrink: 0;
                ">{hours_display} {hours_label} ({percentage:.0f}%)</div>
            </div>
            """

        # Add total summary with productivity insight
        avg_hours_per_user = total_hours / len(hours_data) if len(hours_data) > 1 else total_hours
        
        bars_html += f"""
        <div style="
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #e5e7eb;
        ">
            <div style="
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 8px;
            ">
                <div style="
                    font-size: 12px;
                    font-weight: 600;
                    color: #374151;
                ">Total Active Hours</div>
                <div style="
                    font-size: 14px;
                    font-weight: 700;
                    color: #111827;
                ">{format_hours(total_hours)} hrs</div>
            </div>
        """
        
        if len(hours_data) > 1:
            bars_html += f"""
            <div style="
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <div style="
                    font-size: 11px;
                    color: #6b7280;
                ">Average per User</div>
                <div style="
                    font-size: 12px;
                    font-weight: 600;
                    color: #374151;
                ">{format_hours(avg_hours_per_user)} hrs</div>
            </div>
            """
        
        bars_html += "</div>"

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