# ABOUTME: Lambda function to display token usage breakdown by type
# ABOUTME: Queries CloudWatch Metrics for token distribution across input, output, and cache types

import json
import boto3
import os
from datetime import datetime, timedelta


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
        return {"markdown": "# Token Usage by Type\nDistribution of tokens by operation type"}

    region = os.environ["METRICS_REGION"]

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})

    cloudwatch_client = boto3.client("cloudwatch", region_name=region)

    try:
        # Use dashboard time range if available
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            # Fallback to last 7 days only if no time range provided
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)

        # Convert to datetime for CloudWatch API
        start_dt = datetime.fromtimestamp(start_time / 1000)
        end_dt = datetime.fromtimestamp(end_time / 1000)

        # Define the metrics to query
        token_metrics = [
            ('InputTokens', 'Input Tokens'),
            ('OutputTokens', 'Output Tokens'),
            ('CacheCreationTokens', 'Cache Creation'),
            ('CacheReadTokens', 'Cache Read')
        ]
        
        token_types = []
        
        # Query each metric type
        for metric_name, display_name in token_metrics:
            response = cloudwatch_client.get_metric_statistics(
                Namespace='ClaudeCode',
                MetricName=metric_name,
                StartTime=start_dt,
                EndTime=end_dt,
                Period=300,  # 5-minute periods
                Statistics=['Sum']
            )
            
            # Sum all data points
            total_tokens = sum(point.get('Sum', 0) for point in response.get('Datapoints', []))
            
            if total_tokens > 0:
                token_types.append({
                    "type": display_name,
                    "tokens": total_tokens
                })

        if not token_types:
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
            ">
                <div style="color: white; font-size: 16px; font-weight: 600;">No Token Data</div>
                <div style="color: rgba(255,255,255,0.8); font-size: 12px; margin-top: 8px;">No token usage data available for this period</div>
            </div>
            """

        # Calculate total and percentages
        total_tokens = sum(t["tokens"] for t in token_types)
        
        # Colors for segments
        colors = {
            "Input Tokens": "#3b82f6",
            "Output Tokens": "#ef4444", 
            "Cache Creation": "#10b981",
            "Cache Read": "#8b5cf6"
        }
        
        # Sort by size for better visualization
        token_types.sort(key=lambda x: x["tokens"], reverse=True)
        
        # Build ultra compact bars with text on bars
        legend_html = ""
        max_tokens = max(t["tokens"] for t in token_types) if token_types else 1
        
        for item in token_types:
            percentage = (item["tokens"] / total_tokens * 100) if total_tokens > 0 else 0
            bar_width = (item["tokens"] / max_tokens * 100) if max_tokens > 0 else 0
            color = colors.get(item["type"], "#667eea")
            
            legend_html += f"""
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
                ">{item['type']}</div>
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
                ">{percentage:.1f}% • {format_number(item['tokens'])}</div>
            </div>
            """

        # Create SVG pie chart with percentages
        svg_segments = ""
        cumulative_percent = 0
        
        for i, item in enumerate(token_types):
            percentage = (item["tokens"] / total_tokens * 100) if total_tokens > 0 else 0
            color = colors.get(item["type"], "#667eea")
            
            # Calculate arc path for pie segment
            start_angle = cumulative_percent * 3.6  # Convert percentage to degrees
            end_angle = (cumulative_percent + percentage) * 3.6
            
            # For simplicity, using a colored rectangle to represent percentage
            # In production, you'd use proper SVG arc paths
            cumulative_percent += percentage

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
            {legend_html}
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