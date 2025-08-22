# ABOUTME: Lambda function to display token usage by model
# ABOUTME: Queries DynamoDB using single-partition schema for accurate time-based filtering

import json
import boto3
import os
from datetime import datetime, timedelta
from collections import defaultdict
from boto3.dynamodb.conditions import Key
from decimal import Decimal
import sys
sys.path.append('/opt')
from query_utils import validate_time_range


def format_number(num):
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 10_000:
        return f"{num / 1_000:.0f}K"
    else:
        return f"{num:,.0f}"


def get_model_display_name(model_id):
    """Convert model ID to display name."""
    # Remove common prefixes
    model_display = model_id.replace("us.anthropic.", "").replace("eu.anthropic.", "").replace("apac.anthropic.", "").replace("anthropic.", "")
    
    # Detect model family and version
    model_lower = model_display.lower()
    
    if "opus-4-1" in model_lower or "opus-4.1" in model_lower:
        return "Opus 4.1"
    elif "opus-4" in model_lower:
        return "Opus 4"
    elif "sonnet-4" in model_lower:
        return "Sonnet 4"
    elif "sonnet-3.7" in model_lower or "sonnet-3-7" in model_lower:
        return "Sonnet 3.7"
    elif "sonnet-3.5" in model_lower or "sonnet-3-5" in model_lower:
        return "Sonnet 3.5"
    elif "haiku-3.5" in model_lower or "haiku-3-5" in model_lower:
        return "Haiku 3.5"
    elif "haiku-3" in model_lower or "haiku-3.0" in model_lower:
        return "Haiku 3.0"
    elif "opus" in model_lower:
        return "Opus"
    elif "sonnet" in model_lower:
        return "Sonnet"
    elif "haiku" in model_lower:
        return "Haiku"
    else:
        # Return shortened version if no match
        return model_display.split('-')[0].capitalize()


def get_model_color(model_name):
    """Get color for model based on family."""
    colors = {
        "Opus 4.1": "#3b82f6",  # Blue
        "Opus 4": "#f97316",    # Orange
        "Opus": "#8b5cf6",      # Purple
        "Sonnet 4": "#10b981",  # Green
        "Sonnet 3.7": "#ef4444", # Red
        "Sonnet 3.5": "#ec4899", # Pink
        "Sonnet": "#06b6d4",    # Cyan
        "Haiku 3.5": "#8b5cf6", # Purple
        "Haiku 3.0": "#6366f1", # Indigo
        "Haiku": "#84cc16",     # Lime
    }
    
    # Find the best match
    for key, color in colors.items():
        if key in model_name:
            return color
    
    return "#6b7280"  # Gray default


def lambda_handler(event, context):
    if event.get("describe", False):
        return {"markdown": "# Token Usage by Model\nBreakdown of token consumption by model"}

    metrics_region = os.environ["METRICS_REGION"]
    metrics_table_name = os.environ.get("METRICS_TABLE", "ClaudeCodeMetrics")

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})
    widget_size = widget_context.get("size", {})
    width = widget_size.get("width", 400)
    height = widget_size.get("height", 300)

    # Connect to DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=metrics_region)
    table = dynamodb.Table(metrics_table_name)

    try:
        # Use dashboard time range if available
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            # Fallback to last 7 days
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)

        # Validate time range (max 7 days)
        is_valid, range_days, error_html = validate_time_range(start_time, end_time)
        if not is_valid:
            return error_html

        # Convert timestamps to datetime and ISO format
        start_dt = datetime.fromtimestamp(start_time / 1000)
        end_dt = datetime.fromtimestamp(end_time / 1000)
        start_iso = start_dt.isoformat() + 'Z'
        end_iso = end_dt.isoformat() + 'Z'
        
        # Aggregate tokens by model
        model_totals = defaultdict(float)
        
        print(f"Querying DynamoDB for model data from {start_iso} to {end_iso}")
        
        # Single query for all MODEL_RATE items in the time range
        try:
            response = table.query(
                KeyConditionExpression=Key('pk').eq('METRICS') & 
                                     Key('sk').between(f'{start_iso}#MODEL_RATE#', 
                                                       f'{end_iso}#MODEL_RATE#~')
            )
            
            for item in response.get('Items', []):
                # Extract model ID from sort key
                # SK format is: ISO_TIMESTAMP#MODEL_RATE#model_id
                sk_parts = item['sk'].split('#')
                if len(sk_parts) >= 3 and sk_parts[1] == 'MODEL_RATE':
                    model_id = '#'.join(sk_parts[2:])  # Handle model IDs with # in them
                    
                    # Get tokens (tpm = tokens per minute)
                    tpm = float(item.get('tpm', 0))
                    
                    # Add to model total (tpm represents tokens used in that minute)
                    if tpm > 0:
                        model_totals[model_id] += tpm
            
            # Handle pagination if needed
            while 'LastEvaluatedKey' in response:
                response = table.query(
                    KeyConditionExpression=Key('pk').eq('METRICS') & 
                                         Key('sk').between(f'{start_iso}#MODEL_RATE#', 
                                                           f'{end_iso}#MODEL_RATE#~'),
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                
                for item in response.get('Items', []):
                    sk_parts = item['sk'].split('#')
                    if len(sk_parts) >= 3 and sk_parts[1] == 'MODEL_RATE':
                        model_id = '#'.join(sk_parts[2:])
                        tpm = float(item.get('tpm', 0))
                        if tpm > 0:
                            model_totals[model_id] += tpm
            
        except Exception as e:
            print(f"Error querying model data: {str(e)}")
        
        # Convert to list and sort by usage
        model_data = []
        for model_id, total_tokens in model_totals.items():
            if total_tokens > 0:
                display_name = get_model_display_name(model_id)
                model_data.append({
                    'name': display_name,
                    'tokens': total_tokens,
                    'color': get_model_color(display_name)
                })
        
        # Sort by tokens descending
        model_data.sort(key=lambda x: x['tokens'], reverse=True)
        
        print(f"Found {len(model_data)} models with usage")
        
        if not model_data:
            return """
            <div style="
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100%;
                color: #9ca3af;
                font-size: 14px;
                font-family: 'Amazon Ember', -apple-system, sans-serif;
            ">
                No model usage data available for this period
            </div>
            """
        
        # Calculate max value for scaling and percentages
        max_tokens = max(item['tokens'] for item in model_data) if model_data else 1
        total_tokens = sum(item['tokens'] for item in model_data)
        
        # Limit to top 10 models to prevent overflow
        model_data = model_data[:10]
        
        # Build bar chart HTML - matching top_users style exactly
        bars_html = ""
        for idx, model in enumerate(model_data):
            width_percent = (model['tokens'] / max_tokens * 100) if max_tokens > 0 else 0
            
            percentage = (model['tokens'] / total_tokens * 100) if total_tokens > 0 else 0
            
            bars_html += f"""
            <div style="
                display: flex;
                align-items: center;
                width: 100%;
                height: 24px;
                margin-bottom: 8px;
                font-family: 'Amazon Ember', -apple-system, sans-serif;
            ">
                <div style="
                    width: 80px;
                    padding-right: 12px;
                    font-size: 12px;
                    font-weight: 600;
                    color: #374151;
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    flex-shrink: 0;
                ">{model['name']}</div>
                <div style="
                    flex: 1;
                    position: relative;
                    height: 20px;
                    background: #f3f4f6;
                    border-radius: 4px;
                    overflow: hidden;
                ">
                    <div style="
                        width: {percentage:.1f}%;
                        height: 100%;
                        background: {model['color']};
                        transition: width 0.3s ease;
                    "></div>
                </div>
                <div style="
                    padding-left: 12px;
                    font-size: 11px;
                    font-weight: 600;
                    color: #374151;
                    text-align: right;
                    min-width: 120px;
                    flex-shrink: 0;
                ">{percentage:.1f}% • {format_number(model['tokens'])}</div>
            </div>
            """
        
        return f"""
        <div style="
            padding: 16px;
            height: 100%;
            background: white;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
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
            overflow: hidden;
        ">
            <div style="text-align: center;">
                <div style="color: #991b1b; font-weight: 600; margin-bottom: 4px; font-size: 14px;">Data Unavailable</div>
                <div style="color: #7f1d1d; font-size: 10px;">{error_msg[:100]}</div>
            </div>
        </div>
        """