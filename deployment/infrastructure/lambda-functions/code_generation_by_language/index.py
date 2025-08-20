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
        return {"markdown": "# Code Generation by Language\nCode edits and generations by programming language"}

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
            # Fallback to last 30 days for better data coverage
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)

        # Query for code edit tool decisions by language
        # Validate time range (max 7 days)

        is_valid, range_days, error_html = validate_time_range(start_time, end_time)

        if not is_valid:

            return error_html

        

        query = """
        fields @message
        | filter @message like /code_edit_tool.decision/
        | parse @message /"language":"(?<lang>[^"]*)"/
        | stats sum(claude_code.code_edit_tool.decision) as edits by lang
        | sort edits desc
        | limit 10
        """

        response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query,
        )

        query_id = response['queryId']
        
        # Wait for results with optimized polling
        response = wait_for_query_results(logs_client, query_id)

        query_status = response.get("status", "Unknown")
        languages = []

        if query_status == "Complete":
            if response.get("results") and len(response["results"]) > 0:
                for result in response["results"]:
                    lang = ""
                    count = 0
                    for field in result:
                        if field["field"] == "lang":
                            lang = field["value"]
                        elif field["field"] == "edits":
                            count = int(float(field["value"]))
                    
                    if lang and count:
                        # Language names come directly from the metric, just clean them up
                        # "Plain text" -> "Plain Text", etc.
                        language = lang
                        if language == "Plain text":
                            language = "Plain Text"
                        elif language == "unknown":
                            language = "Unknown"
                        
                        languages.append({"language": language, "count": count})
        elif query_status == "Failed":
            raise Exception(
                f"Query failed: {response.get('statusReason', 'Unknown reason')}"
            )
        elif query_status == "Cancelled":
            raise Exception("Query was cancelled")
        elif query_status in ["Running", "Scheduled"]:
            raise Exception(f"Query timed out: {query_status}")

        if not languages:
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
                <div style="color: white; font-size: 16px; font-weight: 600;">No Code Generation Data</div>
                <div style="color: rgba(255,255,255,0.8); font-size: 12px; margin-top: 8px;">No code edits found for this period</div>
            </div>
            """

        # Calculate max for scaling
        max_count = max(lang["count"] for lang in languages)
        total_edits = sum(lang["count"] for lang in languages)
        
        # Colors for bars - using a gradient based on popularity
        colors = [
            "#3b82f6",  # Blue for most popular
            "#10b981",  # Green
            "#f59e0b",  # Amber
            "#8b5cf6",  # Purple
            "#ef4444",  # Red
            "#06b6d4",  # Cyan
            "#ec4899",  # Pink
            "#f97316"   # Orange
        ]

        # Build horizontal bar chart style display
        bars_html = ""
        for i, lang in enumerate(languages[:8]):  # Limit to top 8
            percentage = (lang["count"] / total_edits * 100) if total_edits > 0 else 0
            bar_width = (lang["count"] / max_count * 100) if max_count > 0 else 0
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
                ">{lang['language']}</div>
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
                ">{percentage:.0f}% • {lang['count']:,}</div>
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
        # Truncate long error messages more intelligently
        if "MalformedQueryException" in error_msg:
            display_error = "Query syntax error"
        elif "unexpected symbol" in error_msg:
            display_error = "Query parsing error"  
        else:
            display_error = error_msg[:80]
            
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
                <div style="color: #7f1d1d; font-size: 10px;">{display_error}</div>
            </div>
        </div>
        """