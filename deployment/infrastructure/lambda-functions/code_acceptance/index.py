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
        return {"markdown": "# Code Acceptance\nShows accept vs reject rates for code suggestions"}

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

        # Validate time range (max 7 days)


        is_valid, range_days, error_html = validate_time_range(start_time, end_time)


        if not is_valid:


            return error_html


        


        query = """
        fields @message
        | filter @message like /code_edit_tool.decision/
        | parse @message /"decision":"(?<decision>[^"]*)"/
        | stats count() as count by decision
        """

        response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query,
        )

        query_id = response['queryId']
        
        # Wait for results with optimized polling
        response = wait_for_query_results(logs_client, query_id)

        query_status = response.get("status", "Unknown")
        decisions = {"accept": 0, "reject": 0}

        if query_status == "Complete":
            if response.get("results") and len(response["results"]) > 0:
                for result in response["results"]:
                    decision = ""
                    count = 0
                    for field in result:
                        if field["field"] == "decision":
                            decision = field["value"]
                        elif field["field"] == "count":
                            count = int(float(field["value"]))
                    
                    if decision and count:
                        if "accept" in decision.lower():
                            decisions["accept"] += count
                        elif "reject" in decision.lower():
                            decisions["reject"] += count
        elif query_status == "Failed":
            raise Exception(
                f"Query failed: {response.get('statusReason', 'Unknown reason')}"
            )
        elif query_status == "Cancelled":
            raise Exception("Query was cancelled")
        elif query_status in ["Running", "Scheduled"]:
            raise Exception(f"Query timed out: {query_status}")

        # If no data, show empty state
        if decisions["accept"] == 0 and decisions["reject"] == 0:
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
                <div style="color: white; font-size: 16px; font-weight: 600;">No Code Decisions</div>
                <div style="color: rgba(255,255,255,0.8); font-size: 12px; margin-top: 8px;">No accept/reject data available for this period</div>
            </div>
            """

        # Calculate percentages
        total_decisions = decisions["accept"] + decisions["reject"]
        accept_rate = (decisions["accept"] / total_decisions * 100) if total_decisions > 0 else 0
        reject_rate = (decisions["reject"] / total_decisions * 100) if total_decisions > 0 else 0
        
        # Build display
        items = [
            {"label": "Accepted", "value": decisions["accept"], "percentage": accept_rate, "color": "#10b981"},
            {"label": "Rejected", "value": decisions["reject"], "percentage": reject_rate, "color": "#ef4444"}
        ]
        
        max_value = max(decisions["accept"], decisions["reject"], 1)
        
        bars_html = ""
        for item in items:
            bar_width = (item["value"] / max_value * 100) if max_value > 0 else 0
            
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
                    width: 80px;
                    padding-right: 8px;
                    font-size: 11px;
                    font-weight: 600;
                    color: #374151;
                    text-align: right;
                    flex-shrink: 0;
                ">{item['label']}</div>
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
                        background: {item['color']};
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
                ">{item['percentage']:.1f}% • {format_number(item['value'])}</div>
            </div>
            """

        # Add acceptance rate highlight - more compact
        bars_html += f"""
        <div style="
            margin-top: 10px;
            padding: 8px 10px;
            background: linear-gradient(135deg, #10b98115 0%, #10b98108 100%);
            border-radius: 4px;
            border-left: 3px solid #10b981;
            display: flex;
            justify-content: space-between;
            align-items: center;
        ">
            <div>
                <div style="
                    font-size: 10px;
                    color: #666;
                ">Acceptance Rate</div>
                <div style="
                    font-size: 18px;
                    font-weight: 700;
                    color: #10b981;
                    line-height: 1;
                ">{accept_rate:.1f}%</div>
            </div>
            <div style="
                font-size: 10px;
                color: #666;
                text-align: right;
            ">{format_number(total_decisions)} total</div>
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