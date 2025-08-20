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
        return {"markdown": "# Operations by Type\nBreakdown of Claude Code operations"}

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
            start_time = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)

        # Query for tool usage which represents actual operations
        # Validate time range (max 7 days)

        is_valid, range_days, error_html = validate_time_range(start_time, end_time)

        if not is_valid:

            return error_html

        

        query = """
        fields @message
        | filter @message like /tool_name/
        | parse @message /"tool_name":"(?<tool>[^"]*)"/
        | stats count() as usage by tool
        | sort usage desc
        | limit 8
        """

        response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query,
        )

        query_id = response['queryId']
        
        # Wait for results with optimized polling
        response = wait_for_query_results(logs_client, query_id)

        query_status = response.get("status", "Unknown")
        operations = []

        if query_status == "Complete":
            if response.get("results") and len(response["results"]) > 0:
                for result in response["results"]:
                    tool_name = ""
                    count = 0
                    for field in result:
                        if field["field"] == "tool":
                            tool_name = field["value"]
                        elif field["field"] == "usage":
                            count = int(float(field["value"]))
                    
                    if tool_name and count:
                        # Clean up tool names for display
                        display_name = tool_name.replace("_", " ").title()
                        operations.append({"name": display_name, "count": count})
        elif query_status == "Failed":
            raise Exception(
                f"Query failed: {response.get('statusReason', 'Unknown reason')}"
            )
        elif query_status == "Cancelled":
            raise Exception("Query was cancelled")
        elif query_status in ["Running", "Scheduled"]:
            raise Exception(f"Query timed out: {query_status}")

        if not operations:
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
                box-sizing: border-box;
                overflow: hidden;
            ">
                <div style="color: white; font-size: 16px; font-weight: 600;">No Operations Data</div>
                <div style="color: rgba(255,255,255,0.8); font-size: 12px; margin-top: 8px;">No tool usage data available for this period</div>
            </div>
            """

        # Calculate max for scaling
        max_count = max(op["count"] for op in operations)
        
        # Colors for bars
        colors = [
            "#667eea", "#764ba2", "#f59e0b", "#10b981",
            "#ef4444", "#06b6d4", "#ec4899", "#8b5cf6"
        ]

        # Build horizontal bar chart with text on bars
        bars_html = ""
        for i, op in enumerate(operations):
            bar_width = (op["count"] / max_count * 100) if max_count > 0 else 0
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
                ">{op['name']}</div>
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
                    font-size: 11px;
                    font-weight: 600;
                    color: #374151;
                    text-align: left;
                    flex-shrink: 0;
                ">{op['count']:,}</div>
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