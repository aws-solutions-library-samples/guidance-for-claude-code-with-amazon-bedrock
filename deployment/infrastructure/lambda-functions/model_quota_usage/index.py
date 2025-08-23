# ABOUTME: Lambda function to display model TPM/RPM usage vs quotas
# ABOUTME: Queries DynamoDB using single-partition schema for real-time rate tracking

import json
import boto3
import os
from datetime import datetime, timedelta, timezone
import time
import sys
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal
sys.path.append('/opt')
from query_utils import validate_time_range
from widget_utils import parse_widget_context, check_describe_mode, get_time_range
from html_utils import generate_error_html, get_status_color

# Quota code mappings for each model
QUOTA_MAPPINGS = {
    "us.anthropic.claude-opus-4-1-20250805-v1:0": {
        "name": "Opus 4.1",
        "tpm_quota_code": "L-BD85BFCD",
        "rpm_quota_code": "L-7EC72A47",
        "regions": ["us-east-1", "us-west-2", "us-east-2"]
    },
    "us.anthropic.claude-opus-4-20250514-v1:0": {
        "name": "Opus 4",
        "tpm_quota_code": "L-29C2B0A3", 
        "rpm_quota_code": "L-C99C7EF6",
        "regions": ["us-east-1", "us-west-2", "us-east-2"]
    },
    "us.anthropic.claude-sonnet-4-20250514-v1:0": {
        "name": "Sonnet 4",
        "tpm_quota_code": "L-59759B4A",
        "rpm_quota_code": "L-559DCC33",
        "regions": ["us-east-1", "us-west-2", "us-east-2"]
    },
    "us.anthropic.claude-3-7-sonnet-20250219-v1:0": {
        "name": "Sonnet 3.7",
        "tpm_quota_code": "L-6E888CC2",
        "rpm_quota_code": "L-3D8CC480",
        "regions": ["us-east-1", "us-west-2", "us-east-2"]
    },
    "eu.anthropic.claude-sonnet-4-20250514-v1:0": {
        "name": "Sonnet 4 (EU)",
        "tpm_quota_code": "L-59759B4A",
        "rpm_quota_code": "L-559DCC33",
        "regions": ["eu-west-1", "eu-west-3", "eu-central-1"]
    },
    "eu.anthropic.claude-3-7-sonnet-20250219-v1:0": {
        "name": "Sonnet 3.7 (EU)",
        "tpm_quota_code": "L-6E888CC2",
        "rpm_quota_code": "L-3D8CC480",
        "regions": ["eu-west-1", "eu-west-3", "eu-central-1"]
    },
    "apac.anthropic.claude-sonnet-4-20250514-v1:0": {
        "name": "Sonnet 4 (APAC)",
        "tpm_quota_code": "L-59759B4A",
        "rpm_quota_code": "L-559DCC33",
        "regions": ["ap-northeast-1", "ap-southeast-1", "ap-southeast-2"]
    },
    "apac.anthropic.claude-3-7-sonnet-20250219-v1:0": {
        "name": "Sonnet 3.7 (APAC)",
        "tpm_quota_code": "L-6E888CC2",
        "rpm_quota_code": "L-3D8CC480",
        "regions": ["ap-northeast-1", "ap-southeast-1", "ap-southeast-2"]
    }
}

# Cache for quota values (1 hour TTL)
_quota_cache = {}
_quota_cache_time = 0
QUOTA_CACHE_TTL = 3600  # 1 hour


def format_number(num):
    """Format numbers for display."""
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.0f}K"
    else:
        return f"{num:.0f}"


def format_compact_number(num):
    """Ultra compact number formatting for tight spaces."""
    if num >= 1_000_000:
        return f"{num/1_000_000:.0f}M"  # No decimal for millions
    elif num >= 10_000:
        return f"{num/1_000:.0f}K"  # No decimal for 10K+
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"  # One decimal for 1-10K
    else:
        return f"{num:.0f}"


def format_timestamp(timestamp_ms):
    """Format timestamp to readable time with UTC indicator."""
    if timestamp_ms is None:
        return ""
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime("%-I:%M %p UTC")


def format_compact_time(timestamp_ms):
    """Compact time format for tight spaces."""
    if timestamp_ms is None:
        return ""
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return dt.strftime("%-I:%M%p UTC")  # 3:25AM UTC


def get_progress_bar_html(percentage, height=20, show_text=True):
    """Generate an HTML progress bar."""
    text_html = f"""
        <div style="
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: {min(11, height-4)}px;
            font-weight: 600;
            color: white;
            text-shadow: 0 1px 2px rgba(0,0,0,0.3);
        ">{percentage:.0f}%</div>
    """ if show_text else ""
    
    return f"""
    <div style="
        width: 100%;
        height: {height}px;
        background: rgba(0,0,0,0.1);
        border-radius: {min(10, height//2)}px;
        overflow: hidden;
        position: relative;
    ">
        <div style="
            width: {min(percentage, 100):.0f}%;
            height: 100%;
            background: linear-gradient(90deg, 
                {get_status_color(percentage)} 0%, 
                {get_status_color(percentage)}dd 100%);
            transition: width 0.3s ease;
        "></div>
        {text_html}
    </div>
    """


def get_micro_progress_bar(percentage, width_chars=8):
    """Text-based micro progress bar for ultra-compact mode."""
    filled = int(width_chars * min(percentage, 100) / 100)
    empty = width_chars - filled
    blocks = "█" * filled + "░" * empty
    color = get_status_color(percentage)
    return f'<span style="color: {color}; font-size: 10px; font-family: monospace;">[{blocks}]</span>'




# get_status_color is now imported from html_utils


def get_service_quota(quota_code, region='us-east-1', quota_name=''):
    """Get service quota value from AWS Service Quotas."""
    global _quota_cache, _quota_cache_time
    
    # Check cache
    cache_key = f"{quota_code}:{region}"
    current_time = time.time()
    
    if cache_key in _quota_cache and (current_time - _quota_cache_time) < QUOTA_CACHE_TTL:
        return _quota_cache[cache_key]
    
    try:
        client = boto3.client('service-quotas', region_name=region)
        response = client.get_service_quota(
            ServiceCode='bedrock',
            QuotaCode=quota_code
        )
        value = response['Quota']['Value']
        
        # Update cache
        _quota_cache[cache_key] = value
        _quota_cache_time = current_time
        
        print(f"Successfully fetched quota {quota_code} ({quota_name}): {value}")
        return value
    except Exception as e:
        print(f"Error getting quota {quota_code} ({quota_name}) in {region}: {str(e)}")
        # Return known default values based on specific quota codes
        # These are fallback values when Service Quotas API is unavailable
        defaults = {
            'L-BD85BFCD': 100000,  # Opus 4.1 TPM
            'L-7EC72A47': 200,     # Opus 4.1 RPM  
            'L-29C2B0A3': 300000,  # Opus 4 V1 TPM
            'L-C99C7EF6': 200,     # Opus 4 V1 RPM
            'L-59759B4A': 200000,  # Sonnet 4 TPM
            'L-559DCC33': 200,     # Sonnet 4 RPM
            'L-6E888CC2': 1000000, # Sonnet 3.7 TPM
            'L-3D8CC480': 250,     # Sonnet 3.7 RPM
        }
        return defaults.get(quota_code, 100000 if 'tpm' in quota_name.lower() else 200)


def get_model_rates_from_dynamodb(table, model_id, start_time, end_time):
    """
    Query DynamoDB for per-minute TPM/RPM data for a specific model.
    Returns: recent_peak_tpm, recent_peak_rpm, avg_5min_tpm, avg_5min_rpm,
             overall_peak_tpm, overall_peak_rpm, overall_peak_tpm_time, overall_peak_rpm_time
    """
    try:
        # Convert timestamps to datetime objects (timezone-aware)
        start_dt = datetime.fromtimestamp(start_time / 1000, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_time / 1000, tz=timezone.utc)
        current_dt = datetime.now(timezone.utc)
        
        # Convert to ISO format for queries
        start_iso = start_dt.isoformat() + 'Z'
        end_iso = end_dt.isoformat() + 'Z'
        
        # Get the last 10 minutes for recent metrics (wider window for better activity detection)
        recent_start_dt = current_dt - timedelta(minutes=10)
        
        all_metrics = []
        
        # Single query for all MODEL_RATE items for this model in time range
        response = table.query(
            KeyConditionExpression=Key('pk').eq('METRICS') & 
                                 Key('sk').between(f'{start_iso}#MODEL_RATE#{model_id}',
                                                   f'{end_iso}#MODEL_RATE#{model_id}~')
        )
        
        for item in response.get('Items', []):
            # Extract model from SK and verify it matches what we're looking for
            sk = item.get('sk', '')
            sk_parts = sk.split('#')
            if len(sk_parts) >= 3 and sk_parts[1] == 'MODEL_RATE':
                item_model = '#'.join(sk_parts[2:])  # Handle model IDs with # in them
                
                # Only process if this is the model we're looking for
                if item_model == model_id:
                    # Parse timestamp from item
                    timestamp_str = item.get('timestamp', '')
                    if timestamp_str:
                        try:
                            metric_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                            all_metrics.append({
                                'datetime': metric_dt,
                                'tpm': float(item.get('tpm', 0)),
                                'rpm': float(item.get('rpm', 0))
                            })
                        except:
                            pass
        
        # Handle pagination if needed
        while 'LastEvaluatedKey' in response:
            response = table.query(
                KeyConditionExpression=Key('pk').eq('METRICS') & 
                                     Key('sk').between(f'{start_iso}#MODEL_RATE#{model_id}',
                                                       f'{end_iso}#MODEL_RATE#{model_id}~'),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            
            for item in response.get('Items', []):
                # Extract model from SK and verify it matches what we're looking for
                sk = item.get('sk', '')
                sk_parts = sk.split('#')
                if len(sk_parts) >= 3 and sk_parts[1] == 'MODEL_RATE':
                    item_model = '#'.join(sk_parts[2:])  # Handle model IDs with # in them
                    
                    # Only process if this is the model we're looking for
                    if item_model == model_id:
                        timestamp_str = item.get('timestamp', '')
                        if timestamp_str:
                            try:
                                metric_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                all_metrics.append({
                                    'datetime': metric_dt,
                                    'tpm': float(item.get('tpm', 0)),
                                    'rpm': float(item.get('rpm', 0))
                                })
                            except:
                                pass
        
        # Calculate metrics
        if not all_metrics:
            return 0, 0, 0, 0, 0, 0, None, None
        
        # Sort by datetime
        all_metrics.sort(key=lambda x: x['datetime'])
        
        # Get recent metrics (last 10 minutes)
        recent_metrics = [m for m in all_metrics if m['datetime'] >= recent_start_dt]
        
        # Calculate recent peak (last 10 minutes)
        if recent_metrics:
            recent_peak_tpm = max(m['tpm'] for m in recent_metrics)
            recent_peak_rpm = max(m['rpm'] for m in recent_metrics)
            # Still calculate 5-minute average for display (using last 5 minutes of data)
            five_min_start = current_dt - timedelta(minutes=5)
            five_min_metrics = [m for m in all_metrics if m['datetime'] >= five_min_start]
            avg_5min_tpm = sum(m['tpm'] for m in five_min_metrics) / len(five_min_metrics) if five_min_metrics else 0
            avg_5min_rpm = sum(m['rpm'] for m in five_min_metrics) / len(five_min_metrics) if five_min_metrics else 0
            
            # If no data in last 5 minutes, model should be considered inactive
            # even if there was data in the 6-10 minute window
            if not five_min_metrics:
                recent_peak_tpm = 0
                recent_peak_rpm = 0
        else:
            # If no recent data, set to 0 to indicate inactive
            recent_peak_tpm = 0
            recent_peak_rpm = 0
            avg_5min_tpm = 0
            avg_5min_rpm = 0
        
        # Calculate overall peaks
        overall_peak_tpm = max(m['tpm'] for m in all_metrics)
        overall_peak_rpm = max(m['rpm'] for m in all_metrics)
        
        # Find when peaks occurred
        tpm_peak_metric = max(all_metrics, key=lambda x: x['tpm'])
        rpm_peak_metric = max(all_metrics, key=lambda x: x['rpm'])
        
        overall_peak_tpm_time = int(tpm_peak_metric['datetime'].timestamp() * 1000)
        overall_peak_rpm_time = int(rpm_peak_metric['datetime'].timestamp() * 1000)
        
        return (recent_peak_tpm, recent_peak_rpm, avg_5min_tpm, avg_5min_rpm,
                overall_peak_tpm, overall_peak_rpm, overall_peak_tpm_time, overall_peak_rpm_time)
        
    except Exception as e:
        print(f"Error getting DynamoDB metrics for {model_id}: {str(e)}")
        return 0, 0, 0, 0, 0, 0, None, None


# Removed - no longer needed since we're using DynamoDB


def lambda_handler(event, context):
    if check_describe_mode(event):
        return {"markdown": "# Model Quota Usage\nTPM and RPM usage vs service quotas for each model"}

    metrics_region = os.environ["METRICS_REGION"]
    metrics_table_name = os.environ.get("METRICS_TABLE", "ClaudeCodeMetrics")
    
    print(f"Starting Model Quota Usage widget - Region: {metrics_region}, Table: {metrics_table_name}")

    widget_ctx = parse_widget_context(event)
    width = widget_ctx['width']
    height = widget_ctx['height']
    time_range = widget_ctx['time_range']
    print(f"Widget dimensions: {width}x{height}")

    # Connect to DynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=metrics_region)
    table = dynamodb.Table(metrics_table_name)

    try:
        # Get time range
        start_time, end_time = get_time_range(time_range, default_hours=1)

        # Validate time range (max 7 days)
        is_valid, range_days, error_html = validate_time_range(start_time, end_time)
        if not is_valid:
            return error_html

        # First pass: Collect all models with usage
        models_with_usage = []
        current_time = datetime.now(timezone.utc)
        
        print(f"Processing {len(QUOTA_MAPPINGS)} models...")
        
        for model_id, config in QUOTA_MAPPINGS.items():
            print(f"Processing model: {model_id} ({config['name']})")
            # Get quotas from Service Quotas API
            # Use first region in the list for quota lookup
            quota_region = config['regions'][0] if config['regions'] else 'us-east-1'
            
            tpm_quota = get_service_quota(config['tpm_quota_code'], quota_region, f"{config['name']} TPM")
            rpm_quota = get_service_quota(config['rpm_quota_code'], quota_region, f"{config['name']} RPM")
            
            # Get usage metrics from DynamoDB
            (recent_peak_tpm, recent_peak_rpm, avg_5min_tpm, avg_5min_rpm,
             overall_peak_tpm, overall_peak_rpm, overall_peak_tpm_time, overall_peak_rpm_time) = \
                get_model_rates_from_dynamodb(table, model_id, start_time, end_time)
            
            # Skip models with absolutely no usage in the time range
            if overall_peak_tpm == 0 and overall_peak_rpm == 0:
                continue
            
            # Determine if model is currently active (has usage in last 10 minutes)
            is_active = recent_peak_tpm > 0 or recent_peak_rpm > 0
            
            # Calculate how long ago the model was last active
            last_active_text = "Active now" if is_active else "No recent activity"
            if not is_active and (overall_peak_tpm_time or overall_peak_rpm_time):
                # Use the most recent peak time
                last_peak_time = max(filter(None, [overall_peak_tpm_time, overall_peak_rpm_time]))
                last_peak_dt = datetime.fromtimestamp(last_peak_time / 1000, tz=timezone.utc)
                minutes_ago = int((current_time - last_peak_dt).total_seconds() / 60)
                if minutes_ago < 60:
                    last_active_text = f"Last active {minutes_ago}m ago"
                elif minutes_ago < 1440:
                    hours_ago = minutes_ago // 60
                    last_active_text = f"Last active {hours_ago}h ago"
                else:
                    last_active_text = "Inactive"
            
            # Calculate percentages based on recent peak values for display
            tpm_percentage = (recent_peak_tpm / tpm_quota * 100) if tpm_quota > 0 else 0
            rpm_percentage = (recent_peak_rpm / rpm_quota * 100) if rpm_quota > 0 else 0
            
            # Calculate overall peak percentages
            tpm_peak_percentage = (overall_peak_tpm / tpm_quota * 100) if tpm_quota > 0 else 0
            rpm_peak_percentage = (overall_peak_rpm / rpm_quota * 100) if rpm_quota > 0 else 0
            
            # Store model data for rendering
            models_with_usage.append({
                'model_id': model_id,
                'name': config['name'],
                'is_active': is_active,
                'last_active_text': last_active_text,
                'tpm': {
                    'recent_peak': recent_peak_tpm,
                    'avg_5min': avg_5min_tpm,
                    'overall_peak': overall_peak_tpm,
                    'overall_peak_time': overall_peak_tpm_time,
                    'quota': tpm_quota,
                    'percentage': tpm_percentage,
                    'peak_percentage': tpm_peak_percentage
                },
                'rpm': {
                    'recent_peak': recent_peak_rpm,
                    'avg_5min': avg_5min_rpm,
                    'overall_peak': overall_peak_rpm,
                    'overall_peak_time': overall_peak_rpm_time,
                    'quota': rpm_quota,
                    'percentage': rpm_percentage,
                    'peak_percentage': rpm_peak_percentage
                }
            })
        
        # Sort models: active first, then by name
        models_with_usage.sort(key=lambda x: (not x['is_active'], x['name']))
        
        # Determine layout based on model count and available space
        model_count = len(models_with_usage)
        print(f"Rendering {model_count} models with usage")
        
        if model_count == 0:
            # Clean empty state matching other widgets
            return """
            <div style="
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100%;
                background: white;
                border-radius: 8px;
                font-family: 'Amazon Ember', -apple-system, sans-serif;
            ">
                <div style="
                    color: #9ca3af;
                    font-size: 14px;
                ">No model usage detected in the selected time range</div>
            </div>
            """
        else:
            # Calculate available space per model
            space_per_model = height / model_count if model_count > 0 else height
            
            # Dynamic sizing based on model count and available space
            if model_count == 1 and space_per_model > 200:
                # Single model with plenty of space - detailed view
                layout_type = "detailed"
                container_padding = 12
            elif model_count == 2 and space_per_model > 120:
                # Two models - enhanced readable view
                layout_type = "enhanced"
                container_padding = 10
            elif model_count <= 3 and space_per_model > 80:
                # 2-3 models - balanced view
                layout_type = "balanced"
                container_padding = 8
            elif model_count <= 4:
                # 3-4 models - compact but readable
                layout_type = "compact"
                container_padding = 6
            else:
                # 5+ models - dense layout
                layout_type = "dense"
                container_padding = 4
            
            # Build HTML based on layout type
            models_html = ""
            
            for idx, model in enumerate(models_with_usage):
                # Determine colors based on usage (use peak percentage for inactive models)
                tpm_color = get_status_color(model['tpm']['percentage'] if model['is_active'] else model['tpm']['peak_percentage'])
                rpm_color = get_status_color(model['rpm']['percentage'] if model['is_active'] else model['rpm']['peak_percentage'])
                
                # Apply fade effect for inactive models
                opacity = "1" if model['is_active'] else "0.6"
                bg_opacity = "100%" if model['is_active'] else "60%"
                
                # Add margin between models
                margin_bottom = 8 if idx < model_count - 1 else 0
                
                if layout_type == "detailed":
                    # Single model - detailed view with all metrics clearly visible
                    tpm_value = format_number(model['tpm']['recent_peak']) if model['is_active'] else "—"
                    rpm_value = f"{model['rpm']['recent_peak']:.0f}" if model['is_active'] else "—"
                    
                    models_html += f"""
                    <div style="
                        background: linear-gradient(135deg, #1f2937 0%, #111827 {bg_opacity});
                        border-radius: 8px;
                        padding: 16px;
                        margin-bottom: {margin_bottom}px;
                        opacity: {opacity};
                        transition: opacity 0.3s ease;
                    ">
                        <div style="
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            margin-bottom: 12px;
                        ">
                            <div style="color: white; font-size: 16px; font-weight: 600;">{model['name']}</div>
                            <div style="color: {'#10b981' if model['is_active'] else '#9ca3af'}; font-size: 12px;">
                                {model['last_active_text']}
                            </div>
                        </div>
                        
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                            <!-- TPM -->
                            <div style="
                                background: {tpm_color}22;
                                border: 1px solid {tpm_color}44;
                                border-radius: 6px;
                                padding: 12px;
                            ">
                                <div style="color: white; font-size: 11px; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">
                                    Tokens Per Minute (TPM)
                                </div>
                                <div style="color: white; font-size: 28px; font-weight: bold; margin-bottom: 8px;">{tpm_value}</div>
                                <div style="font-size: 12px; color: rgba(255,255,255,0.9); line-height: 1.4;">
                                    <div>5m Avg: {format_number(model['tpm']['avg_5min']) if model['is_active'] else '—'}</div>
                                    <div>Peak: {format_number(model['tpm']['overall_peak'])} @ {format_compact_time(model['tpm']['overall_peak_time'])}</div>
                                    <div>Quota: {format_number(model['tpm']['quota'])}</div>
                                </div>
                                <div style="margin-top: 8px;">
                                    {get_progress_bar_html(model['tpm']['percentage'] if model['is_active'] else model['tpm']['peak_percentage'], 16)}
                                </div>
                            </div>
                            
                            <!-- RPM -->
                            <div style="
                                background: {rpm_color}22;
                                border: 1px solid {rpm_color}44;
                                border-radius: 6px;
                                padding: 12px;
                            ">
                                <div style="color: white; font-size: 11px; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">
                                    Requests Per Minute (RPM)
                                </div>
                                <div style="color: white; font-size: 28px; font-weight: bold; margin-bottom: 8px;">{rpm_value}</div>
                                <div style="font-size: 12px; color: rgba(255,255,255,0.9); line-height: 1.4;">
                                    <div>5m Avg: {f"{model['rpm']['avg_5min']:.0f}" if model['is_active'] else '—'}</div>
                                    <div>Peak: {model['rpm']['overall_peak']:.0f} @ {format_compact_time(model['rpm']['overall_peak_time'])}</div>
                                    <div>Quota: {model['rpm']['quota']:.0f}</div>
                                </div>
                                <div style="margin-top: 8px;">
                                    {get_progress_bar_html(model['rpm']['percentage'] if model['is_active'] else model['rpm']['peak_percentage'], 16)}
                                </div>
                            </div>
                        </div>
                    </div>
                    """
                    
                elif layout_type == "enhanced":
                    # 2 models - enhanced readable view with clear labels
                    tpm_current = format_number(model['tpm']['recent_peak']) if model['is_active'] else "—"
                    rpm_current = f"{model['rpm']['recent_peak']:.0f}" if model['is_active'] else "—"
                    
                    models_html += f"""
                    <div style="
                        background: linear-gradient(135deg, #1f2937 0%, #111827 {bg_opacity});
                        border-radius: 6px;
                        padding: 12px;
                        margin-bottom: {margin_bottom}px;
                        opacity: {opacity};
                        transition: opacity 0.3s ease;
                    ">
                        <div style="
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            margin-bottom: 8px;
                        ">
                            <div style="color: white; font-size: 14px; font-weight: 600;">{model['name']}</div>
                            <div style="color: {'#10b981' if model['is_active'] else '#9ca3af'}; font-size: 11px;">
                                {model['last_active_text']}
                            </div>
                        </div>
                        
                        <!-- TPM Row -->
                        <div style="
                            display: flex;
                            align-items: center;
                            margin-bottom: 6px;
                            padding: 6px;
                            background: {tpm_color}11;
                            border-radius: 4px;
                        ">
                            <span style="color: {tpm_color}; width: 45px; font-size: 12px; font-weight: 600;">TPM</span>
                            <div style="flex: 1; display: flex; align-items: center; gap: 12px; color: white; font-size: 12px;">
                                <span><b>Now:</b> {tpm_current}</span>
                                <span style="color: rgba(255,255,255,0.8);"><b>Avg:</b> {format_number(model['tpm']['avg_5min']) if model['is_active'] else '—'}</span>
                                <span style="color: rgba(255,255,255,0.8);"><b>Peak:</b> {format_number(model['tpm']['overall_peak'])} @ {format_compact_time(model['tpm']['overall_peak_time'])}</span>
                                <span style="color: rgba(255,255,255,0.7);"><b>Limit:</b> {format_number(model['tpm']['quota'])}</span>
                            </div>
                            <div style="width: 100px; margin: 0 8px;">
                                {get_progress_bar_html(model['tpm']['percentage'] if model['is_active'] else model['tpm']['peak_percentage'], 12, False)}
                            </div>
                            <span style="color: {tpm_color}; font-weight: bold; font-size: 12px; width: 40px; text-align: right;">
                                {(model['tpm']['percentage'] if model['is_active'] else model['tpm']['peak_percentage']):.0f}%
                            </span>
                        </div>
                        
                        <!-- RPM Row -->
                        <div style="
                            display: flex;
                            align-items: center;
                            padding: 6px;
                            background: {rpm_color}11;
                            border-radius: 4px;
                        ">
                            <span style="color: {rpm_color}; width: 45px; font-size: 12px; font-weight: 600;">RPM</span>
                            <div style="flex: 1; display: flex; align-items: center; gap: 12px; color: white; font-size: 12px;">
                                <span><b>Now:</b> {rpm_current}</span>
                                <span style="color: rgba(255,255,255,0.8);"><b>Avg:</b> {f"{model['rpm']['avg_5min']:.0f}" if model['is_active'] else '—'}</span>
                                <span style="color: rgba(255,255,255,0.8);"><b>Peak:</b> {model['rpm']['overall_peak']:.0f} @ {format_compact_time(model['rpm']['overall_peak_time'])}</span>
                                <span style="color: rgba(255,255,255,0.7);"><b>Limit:</b> {model['rpm']['quota']:.0f}</span>
                            </div>
                            <div style="width: 100px; margin: 0 8px;">
                                {get_progress_bar_html(model['rpm']['percentage'] if model['is_active'] else model['rpm']['peak_percentage'], 12, False)}
                            </div>
                            <span style="color: {rpm_color}; font-weight: bold; font-size: 12px; width: 40px; text-align: right;">
                                {(model['rpm']['percentage'] if model['is_active'] else model['rpm']['peak_percentage']):.0f}%
                            </span>
                        </div>
                    </div>
                    """
                    
                elif layout_type in ["balanced", "compact", "dense"]:
                    # 3+ models - compact but readable view
                    font_size = 12 if layout_type == "balanced" else 11
                    padding = 8 if layout_type == "balanced" else 6
                    
                    tpm_current = format_compact_number(model['tpm']['recent_peak']) if model['is_active'] else "—"
                    rpm_current = f"{model['rpm']['recent_peak']:.0f}" if model['is_active'] else "—"
                    
                    models_html += f"""
                    <div style="
                        background: linear-gradient(135deg, #1f2937 0%, #111827 {bg_opacity});
                        border-radius: 4px;
                        padding: {padding}px;
                        margin-bottom: {margin_bottom}px;
                        opacity: {opacity};
                        transition: opacity 0.3s ease;
                    ">
                        <div style="
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            margin-bottom: 4px;
                        ">
                            <div style="color: white; font-size: {font_size}px; font-weight: 600;">{model['name']}</div>
                            <div style="color: {'#10b981' if model['is_active'] else '#9ca3af'}; font-size: 10px;">
                                {model['last_active_text']}
                            </div>
                        </div>
                        
                        <div style="
                            display: flex;
                            align-items: center;
                            font-size: {font_size - 1}px;
                            gap: 2px;
                        ">
                            <!-- TPM Section -->
                            <span style="color: {tpm_color}; font-weight: 600; margin-right: 6px;">TPM:</span>
                            <span style="color: white;">{tpm_current}</span>
                            <span style="color: #6b7280; margin: 0 4px;">|</span>
                            <span style="color: rgba(255,255,255,0.7); font-size: {font_size - 2}px;">
                                Peak: {format_compact_number(model['tpm']['overall_peak'])}@{format_compact_time(model['tpm']['overall_peak_time'])}
                            </span>
                            <span style="color: #6b7280; margin: 0 4px;">|</span>
                            <span style="color: rgba(255,255,255,0.6); font-size: {font_size - 2}px;">
                                Limit: {format_compact_number(model['tpm']['quota'])}
                            </span>
                            <div style="width: 60px; margin: 0 6px;">
                                {get_progress_bar_html(model['tpm']['percentage'] if model['is_active'] else model['tpm']['peak_percentage'], 8, False)}
                            </div>
                            <span style="color: {tpm_color}; font-weight: bold; margin-right: 12px;">
                                {(model['tpm']['percentage'] if model['is_active'] else model['tpm']['peak_percentage']):.0f}%
                            </span>
                            
                            <!-- RPM Section -->
                            <span style="color: {rpm_color}; font-weight: 600; margin-right: 6px;">RPM:</span>
                            <span style="color: white;">{rpm_current}</span>
                            <span style="color: #6b7280; margin: 0 4px;">|</span>
                            <span style="color: rgba(255,255,255,0.7); font-size: {font_size - 2}px;">
                                Peak: {model['rpm']['overall_peak']:.0f}@{format_compact_time(model['rpm']['overall_peak_time'])}
                            </span>
                            <span style="color: #6b7280; margin: 0 4px;">|</span>
                            <span style="color: rgba(255,255,255,0.6); font-size: {font_size - 2}px;">
                                Limit: {model['rpm']['quota']:.0f}
                            </span>
                            <div style="width: 60px; margin: 0 6px;">
                                {get_progress_bar_html(model['rpm']['percentage'] if model['is_active'] else model['rpm']['peak_percentage'], 8, False)}
                            </div>
                            <span style="color: {rpm_color}; font-weight: bold;">
                                {(model['rpm']['percentage'] if model['is_active'] else model['rpm']['peak_percentage']):.0f}%
                            </span>
                        </div>
                    </div>
                    """
        
        # Build final HTML
        html = f"""
        <div style="
            padding: {container_padding}px;
            height: 100%;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            background: #f9fafb;
            box-sizing: border-box;
            overflow: hidden;
        ">
            {models_html}
        </div>
        """

        return html

    except Exception as e:
        return generate_error_html(str(e))