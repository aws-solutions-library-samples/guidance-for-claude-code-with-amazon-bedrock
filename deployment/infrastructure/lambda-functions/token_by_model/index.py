import json
import boto3
import os
from datetime import datetime, timedelta
import time
import sys
sys.path.append('/opt')
from query_utils import rate_limited_start_query, wait_for_query_results, validate_time_range
import math
from urllib.parse import quote


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
        return {
            "markdown": "# Token Usage by Model\nToken distribution across model versions"
        }

    log_group = os.environ["METRICS_LOG_GROUP"]
    region = os.environ["METRICS_REGION"]

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})

    logs_client = boto3.client("logs", region_name=region)

    try:
        # Use dashboard time range if available
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            # Fallback to last 7 days only if no time range provided
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)

        # Validate time range (max 7 days)


        is_valid, range_days, error_html = validate_time_range(start_time, end_time)


        if not is_valid:


            return error_html


        


        query = """
        fields @message
        | filter @message like /claude_code.token.usage/
        | parse @message /"model":"(?<model>[^"]*)"/
        | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
        | stats sum(tokens) as total by model
        | sort total desc
        """

        response = rate_limited_start_query(logs_client, log_group, start_time, end_time, query,
        )

        query_id = response['queryId']
        
        # Wait for results with optimized polling
        response = wait_for_query_results(logs_client, query_id)

        query_status = response.get("status", "Unknown")
        model_aggregates = {}

        if query_status == "Complete":
            if response.get("results") and len(response["results"]) > 0:
                for result in response["results"]:
                    model_raw = ""
                    total = 0
                    for field in result:
                        if field["field"] == "model":
                            model_raw = field["value"]
                        elif field["field"] == "total":
                            total = float(field["value"])

                    if model_raw and total:
                        model_name = model_raw.replace("us.anthropic.", "").replace(
                            "anthropic.", ""
                        )
                        # More specific version detection - check all patterns
                        model_lower = model_name.lower()
                        
                        # Opus versions
                        if "opus-4-1" in model_lower or "opus-4.1" in model_lower:
                            model_family = "Opus 4.1"
                        elif "opus-4" in model_lower or "opus-4.0" in model_lower:
                            model_family = "Opus 4"
                        # Sonnet versions - check both orders
                        elif "sonnet-4" in model_lower or "sonnet-4.0" in model_lower:
                            model_family = "Sonnet 4"
                        elif "sonnet-3.7" in model_lower or "sonnet-3-7" in model_lower or "3.7" in model_lower and "sonnet" in model_lower or "3-7" in model_lower and "sonnet" in model_lower:
                            model_family = "Sonnet 3.7"
                        elif "sonnet-3.5" in model_lower or "sonnet-3-5" in model_lower or "3.5" in model_lower and "sonnet" in model_lower or "3-5" in model_lower and "sonnet" in model_lower:
                            model_family = "Sonnet 3.5"
                        # Haiku versions - check both orders
                        elif "haiku-3.5" in model_lower or "haiku-3-5" in model_lower or "3.5" in model_lower and "haiku" in model_lower or "3-5" in model_lower and "haiku" in model_lower:
                            model_family = "Haiku 3.5"
                        elif "haiku-3" in model_lower or "haiku-3.0" in model_lower:
                            model_family = "Haiku 3.0"
                        # Generic fallbacks (should rarely be reached now)
                        elif "opus" in model_lower:
                            model_family = "Opus"
                        elif "sonnet" in model_lower:
                            model_family = "Sonnet"
                        elif "haiku" in model_lower:
                            model_family = "Haiku"
                        else:
                            model_family = (
                                model_name.split("-")[2]
                                if len(model_name.split("-")) > 2
                                else model_name
                            )

                        if model_family in model_aggregates:
                            model_aggregates[model_family] += total
                        else:
                            model_aggregates[model_family] = total
        elif query_status == "Failed":
            raise Exception(
                f"Query failed: {response.get('statusReason', 'Unknown reason')}"
            )
        elif query_status == "Cancelled":
            raise Exception("Query was cancelled")
        else:
            raise Exception(f"Query did not complete: {query_status}")

        if not model_aggregates:
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
                    font-size: 16px;
                    font-weight: 600;
                    color: white;
                    text-shadow: 0 2px 4px rgba(0,0,0,0.2);
                ">No Model Data</div>
                <div style="
                    font-size: 11px;
                    color: rgba(255,255,255,0.8);
                    margin-top: 8px;
                ">No token usage data available</div>
            </div>
            """

        # Convert to list and sort
        models = []
        total_sum = sum(model_aggregates.values())
        for model, tokens in model_aggregates.items():
            percentage = (tokens / total_sum * 100) if total_sum > 0 else 0
            models.append({"model": model, "tokens": tokens, "percentage": percentage})
        
        models.sort(key=lambda x: x["tokens"], reverse=True)
        
        # Colors for different models
        color_map = {
            "Opus 4.1": "#667eea",
            "Opus 4": "#764ba2", 
            "Opus": "#8b5cf6",
            "Sonnet 4": "#d97706",
            "Sonnet 3.7": "#f59e0b",
            "Sonnet 3.5": "#ef4444",
            "Sonnet": "#ec4899",
            "Haiku 3.5": "#10b981",
            "Haiku 3.0": "#06b6d4",
            "Haiku": "#3b82f6"
        }
        
        # Build bar chart
        bars_html = ""
        max_tokens = models[0]["tokens"] if models else 1
        
        for model_data in models[:8]:  # Limit to top 8
            bar_width = (model_data["tokens"] / max_tokens * 100) if max_tokens > 0 else 0
            color = color_map.get(model_data["model"], "#667eea")
            
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
                    width: 90px;
                    padding-right: 8px;
                    font-size: 11px;
                    font-weight: 600;
                    color: #374151;
                    text-align: right;
                    flex-shrink: 0;
                ">{model_data['model']}</div>
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
                ">{model_data['percentage']:.1f}% • {format_number(model_data['tokens'])}</div>
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