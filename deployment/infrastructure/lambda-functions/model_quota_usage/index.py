# ABOUTME: Lambda function to display model TPM/RPM usage vs quotas
# ABOUTME: Queries Service Quotas API and shows usage percentages with progress bars

import json
import boto3
import os
from datetime import datetime, timedelta
import time
import sys
sys.path.append('/opt')
from query_utils import rate_limited_start_query, wait_for_query_results, validate_time_range
try:
    from metrics_utils import get_metric_statistics, get_latest_metric_value, check_metrics_available
except ImportError:
    # Metrics utils not available, will fall back to logs
    pass

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


def format_timestamp(timestamp_ms):
    """Format timestamp to readable time with UTC indicator."""
    if timestamp_ms is None:
        return ""
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime("%-I:%M %p UTC")


def get_progress_bar_html(percentage, height=20):
    """Generate an HTML progress bar."""
    return f"""
    <div style="
        width: 100%;
        height: {height}px;
        background: rgba(0,0,0,0.1);
        border-radius: 10px;
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
        <div style="
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 600;
            color: white;
            text-shadow: 0 1px 2px rgba(0,0,0,0.3);
        ">{percentage:.0f}%</div>
    </div>
    """




def get_status_color(percentage):
    """Get color based on usage percentage."""
    if percentage >= 90:
        return "#ef4444"  # Red
    elif percentage >= 70:
        return "#f59e0b"  # Yellow
    else:
        return "#10b981"  # Green


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


def get_usage_metrics_from_cloudwatch(cloudwatch_client, model_id, start_time, end_time):
    """Get current and peak TPM/RPM from CloudWatch Metrics."""
    try:
        # Get TPM from metrics
        tpm_dimensions = [{'Name': 'Model', 'Value': model_id}]
        
        # Get current TPM (most recent data point)
        tpm_current = get_latest_metric_value(
            cloudwatch_client,
            'TokensPerMinute',
            tpm_dimensions,
            'Sum',
            lookback_minutes=10
        ) or 0
        
        # Get peak TPM over the time range
        tpm_datapoints = get_metric_statistics(
            cloudwatch_client,
            'TokensPerMinute',
            start_time,
            end_time,
            tpm_dimensions,
            'Maximum',
            300  # 5-minute periods
        )
        
        tpm_peak = tpm_current
        tpm_peak_time = None
        if tpm_datapoints:
            max_point = max(tpm_datapoints, key=lambda x: x.get('Maximum', 0))
            tpm_peak = max_point.get('Maximum', tpm_current)
            tpm_peak_time = int(max_point['Timestamp'].timestamp() * 1000) if 'Timestamp' in max_point else None
        
        # Get RPM from metrics
        rpm_current = get_latest_metric_value(
            cloudwatch_client,
            'RequestsPerMinute',
            tpm_dimensions,
            'Sum',
            lookback_minutes=10
        ) or 0
        
        # Get peak RPM over the time range
        rpm_datapoints = get_metric_statistics(
            cloudwatch_client,
            'RequestsPerMinute',
            start_time,
            end_time,
            tpm_dimensions,
            'Maximum',
            300
        )
        
        rpm_peak = rpm_current
        rpm_peak_time = None
        if rpm_datapoints:
            max_point = max(rpm_datapoints, key=lambda x: x.get('Maximum', 0))
            rpm_peak = max_point.get('Maximum', rpm_current)
            rpm_peak_time = int(max_point['Timestamp'].timestamp() * 1000) if 'Timestamp' in max_point else None
        
        return tpm_current, tpm_peak, tpm_peak_time, rpm_current, rpm_peak, rpm_peak_time
        
    except Exception as e:
        print(f"Error getting metrics for {model_id}: {str(e)}")
        return None  # Signal to fall back to logs


def get_usage_metrics(logs_client, log_group, model_id, start_time, end_time, region):
    """Get current and peak TPM/RPM for a specific model."""
    
    # Current TPM Query - get last minute's tokens
    tpm_current_query = f"""
    fields @timestamp, @message
    | filter @message like /claude_code.token.usage/
    | filter @message like /{model_id}/
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | stats sum(tokens) as total_tokens by bin(1m) as time
    | sort time desc
    | limit 1
    """
    
    # Peak TPM Query - get maximum tokens per minute in time range with timestamp
    tpm_peak_query = f"""
    fields @timestamp, @message
    | filter @message like /claude_code.token.usage/
    | filter @message like /{model_id}/
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | stats sum(tokens) as total_tokens by bin(1m) as time
    | sort total_tokens desc
    | limit 1
    """
    
    # Current RPM Query - get last minute's requests
    rpm_current_query = f"""
    fields @timestamp, @message
    | filter @message like /type":"input/
    | filter @message like /{model_id}/
    | stats count() as requests by bin(1m) as time
    | sort time desc
    | limit 1
    """
    
    # Peak RPM Query - get maximum requests per minute in time range with timestamp
    rpm_peak_query = f"""
    fields @timestamp, @message
    | filter @message like /type":"input/
    | filter @message like /{model_id}/
    | stats count() as requests by bin(1m) as time
    | sort requests desc
    | limit 1
    """
    
    try:
        # Run current TPM query
        tpm_current_response = rate_limited_start_query(
            logs_client, log_group, start_time, end_time, tpm_current_query
        )
        tpm_current_result = wait_for_query_results(logs_client, tpm_current_response['queryId'])
        
        tpm_current = 0
        if tpm_current_result.get('status') == 'Complete' and tpm_current_result.get('results'):
            for field in tpm_current_result['results'][0]:
                if field['field'] == 'total_tokens':
                    tpm_current = float(field['value'])
        
        # Run peak TPM query
        tpm_peak_response = rate_limited_start_query(
            logs_client, log_group, start_time, end_time, tpm_peak_query
        )
        tpm_peak_result = wait_for_query_results(logs_client, tpm_peak_response['queryId'])
        
        tpm_peak = tpm_current  # Default to current if no peak found
        tpm_peak_time = None
        if tpm_peak_result.get('status') == 'Complete' and tpm_peak_result.get('results'):
            for field in tpm_peak_result['results'][0]:
                if field['field'] == 'total_tokens':
                    tpm_peak = float(field['value'])
                elif field['field'] == 'time':
                    # Parse timestamp string to milliseconds
                    try:
                        dt = datetime.strptime(field['value'], '%Y-%m-%d %H:%M:%S.%f')
                        tpm_peak_time = int(dt.timestamp() * 1000)
                    except:
                        tpm_peak_time = None
        
        # Run current RPM query
        rpm_current_response = rate_limited_start_query(
            logs_client, log_group, start_time, end_time, rpm_current_query
        )
        rpm_current_result = wait_for_query_results(logs_client, rpm_current_response['queryId'])
        
        rpm_current = 0
        if rpm_current_result.get('status') == 'Complete' and rpm_current_result.get('results'):
            for field in rpm_current_result['results'][0]:
                if field['field'] == 'requests':
                    rpm_current = float(field['value'])
        
        # Run peak RPM query
        rpm_peak_response = rate_limited_start_query(
            logs_client, log_group, start_time, end_time, rpm_peak_query
        )
        rpm_peak_result = wait_for_query_results(logs_client, rpm_peak_response['queryId'])
        
        rpm_peak = rpm_current  # Default to current if no peak found
        rpm_peak_time = None
        if rpm_peak_result.get('status') == 'Complete' and rpm_peak_result.get('results'):
            for field in rpm_peak_result['results'][0]:
                if field['field'] == 'requests':
                    rpm_peak = float(field['value'])
                elif field['field'] == 'time':
                    # Parse timestamp string to milliseconds  
                    try:
                        dt = datetime.strptime(field['value'], '%Y-%m-%d %H:%M:%S.%f')
                        rpm_peak_time = int(dt.timestamp() * 1000)
                    except:
                        rpm_peak_time = None
        
        return tpm_current, tpm_peak, tpm_peak_time, rpm_current, rpm_peak, rpm_peak_time
        
    except Exception as e:
        print(f"Error getting usage for {model_id}: {str(e)}")
        return 0, 0, None, 0, 0, None


def lambda_handler(event, context):
    if event.get("describe", False):
        return {"markdown": "# Model Quota Usage\nTPM and RPM usage vs service quotas for each model"}

    log_group = os.environ["METRICS_LOG_GROUP"]
    metrics_region = os.environ["METRICS_REGION"]
    
    print(f"Starting Model Quota Usage widget - Log Group: {log_group}, Region: {metrics_region}")

    widget_context = event.get("widgetContext", {})
    time_range = widget_context.get("timeRange", {})

    logs_client = boto3.client("logs", region_name=metrics_region)
    cloudwatch_client = boto3.client("cloudwatch", region_name=metrics_region)
    
    # Check if metrics are available
    use_metrics = False
    try:
        if 'metrics_utils' in sys.modules:
            use_metrics = check_metrics_available(cloudwatch_client)
            if use_metrics:
                print("Using CloudWatch Metrics for model quota data")
            else:
                print("CloudWatch Metrics not available, falling back to logs")
    except:
        print("Metrics utils not available, using logs")

    try:
        # Use dashboard time range
        if "start" in time_range and "end" in time_range:
            start_time = time_range["start"]
            end_time = time_range["end"]
        else:
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)

        # Validate time range (max 7 days)
        is_valid, range_days, error_html = validate_time_range(start_time, end_time)
        if not is_valid:
            return error_html

        # Build HTML for display
        models_html = ""
        models_processed = 0
        
        print(f"Processing {len(QUOTA_MAPPINGS)} models...")
        
        for model_id, config in QUOTA_MAPPINGS.items():
            print(f"Processing model: {model_id} ({config['name']})")
            # Get quotas from Service Quotas API
            # Use first region in the list for quota lookup
            quota_region = config['regions'][0] if config['regions'] else 'us-east-1'
            
            tpm_quota = get_service_quota(config['tpm_quota_code'], quota_region, f"{config['name']} TPM")
            rpm_quota = get_service_quota(config['rpm_quota_code'], quota_region, f"{config['name']} RPM")
            
            # Get current and peak usage - try metrics first, fall back to logs
            if use_metrics:
                result = get_usage_metrics_from_cloudwatch(
                    cloudwatch_client, model_id, start_time, end_time
                )
                if result is not None:
                    tpm_current, tpm_peak, tpm_peak_time, rpm_current, rpm_peak, rpm_peak_time = result
                else:
                    # Fall back to logs if metrics failed
                    tpm_current, tpm_peak, tpm_peak_time, rpm_current, rpm_peak, rpm_peak_time = get_usage_metrics(
                        logs_client, log_group, model_id, start_time, end_time, metrics_region
                    )
            else:
                # Use logs directly
                tpm_current, tpm_peak, tpm_peak_time, rpm_current, rpm_peak, rpm_peak_time = get_usage_metrics(
                    logs_client, log_group, model_id, start_time, end_time, metrics_region
                )
            
            # Skip models with no usage
            if tpm_current == 0 and tpm_peak == 0 and rpm_current == 0 and rpm_peak == 0:
                continue
            
            # Calculate percentages based on CURRENT values for display
            tpm_percentage = (tpm_current / tpm_quota * 100) if tpm_quota > 0 else 0
            rpm_percentage = (rpm_current / rpm_quota * 100) if rpm_quota > 0 else 0
            
            # Calculate peak percentages
            tpm_peak_percentage = (tpm_peak / tpm_quota * 100) if tpm_quota > 0 else 0
            rpm_peak_percentage = (rpm_peak / rpm_quota * 100) if rpm_quota > 0 else 0
            
            # Get max percentage to determine overall status color (use peaks for gradient)
            max_percentage = max(tpm_peak_percentage, rpm_peak_percentage)
            
            # Determine gradient color based on peak usage
            if max_percentage >= 90:
                gradient = "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)"  # Red
            elif max_percentage >= 70:
                gradient = "linear-gradient(135deg, #f59e0b 0%, #d97706 100%)"  # Yellow
            else:
                gradient = "linear-gradient(135deg, #10b981 0%, #059669 100%)"  # Green
            
            # Determine individual metric colors based on CURRENT usage
            tpm_color = get_status_color(tpm_percentage)
            rpm_color = get_status_color(rpm_percentage)
            
            # Determine individual background colors (lighter versions)
            tpm_bg_color = tpm_color if tpm_percentage >= 70 else "transparent"
            rpm_bg_color = rpm_color if rpm_percentage >= 70 else "transparent"
            
            # Format peak times with percentage
            tpm_peak_str = f"{format_number(tpm_peak)} @ {format_timestamp(tpm_peak_time)}" if tpm_peak_time else format_number(tpm_peak)
            rpm_peak_str = f"{rpm_peak:.0f} @ {format_timestamp(rpm_peak_time)}" if rpm_peak_time else f"{rpm_peak:.0f}"
            
            # Build HTML for this model  
            models_html += f"""
            <div style="
                margin-bottom: 15px;
                background: linear-gradient(135deg, #1f2937 0%, #111827 100%);
                border-radius: 8px;
                padding: 15px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            ">
                <div style="
                    color: white;
                    font-size: 16px;
                    font-weight: 600;
                    margin-bottom: 12px;
                    text-shadow: 0 1px 2px rgba(0,0,0,0.2);
                ">{config['name']}</div>
                
                <div style="
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 15px;
                ">
                    <!-- TPM Section -->
                    <div style="
                        background: linear-gradient(135deg, {tpm_color}44, {tpm_color}22);
                        border-radius: 6px;
                        padding: 10px;
                        border: 2px solid {tpm_color};
                    ">
                        <div style="
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            margin-bottom: 8px;
                        ">
                            <div>
                                <span style="
                                    color: white;
                                    font-size: 11px;
                                    text-transform: uppercase;
                                    letter-spacing: 0.5px;
                                    display: block;
                                ">TPM</span>
                                <span style="
                                    color: rgba(255,255,255,0.8);
                                    font-size: 9px;
                                ">Tokens/Min</span>
                            </div>
                            <div style="text-align: right;">
                                <span style="
                                    color: white;
                                    font-size: 32px;
                                    font-weight: 700;
                                    display: block;
                                    line-height: 1;
                                ">{format_number(tpm_current)}</span>
                                <span style="
                                    color: rgba(255,255,255,0.8);
                                    font-size: 10px;
                                ">Current</span>
                            </div>
                        </div>
                        
                        {get_progress_bar_html(tpm_percentage, 22)}
                        
                        <div style="
                            margin-top: 8px;
                            padding-top: 8px;
                            border-top: 1px solid rgba(255,255,255,0.1);
                        ">
                            <div style="
                                font-size: 12px;
                                color: white;
                                display: flex;
                                justify-content: space-between;
                                margin-bottom: 2px;
                            ">
                                <span style="font-weight: 600;">Peak: {tpm_peak_str}</span>
                                <span style="opacity: 0.8;">Quota: {format_number(tpm_quota)}</span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- RPM Section -->
                    <div style="
                        background: linear-gradient(135deg, {rpm_color}44, {rpm_color}22);
                        border-radius: 6px;
                        padding: 10px;
                        border: 2px solid {rpm_color};
                    ">
                        <div style="
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            margin-bottom: 8px;
                        ">
                            <div>
                                <span style="
                                    color: white;
                                    font-size: 11px;
                                    text-transform: uppercase;
                                    letter-spacing: 0.5px;
                                    display: block;
                                ">RPM</span>
                                <span style="
                                    color: rgba(255,255,255,0.8);
                                    font-size: 9px;
                                ">Requests/Min</span>
                            </div>
                            <div style="text-align: right;">
                                <span style="
                                    color: white;
                                    font-size: 32px;
                                    font-weight: 700;
                                    display: block;
                                    line-height: 1;
                                ">{rpm_current:.0f}</span>
                                <span style="
                                    color: rgba(255,255,255,0.8);
                                    font-size: 10px;
                                ">Current</span>
                            </div>
                        </div>
                        
                        {get_progress_bar_html(rpm_percentage, 22)}
                        
                        <div style="
                            margin-top: 8px;
                            padding-top: 8px;
                            border-top: 1px solid rgba(255,255,255,0.1);
                        ">
                            <div style="
                                font-size: 12px;
                                color: white;
                                display: flex;
                                justify-content: space-between;
                                margin-bottom: 2px;
                            ">
                                <span style="font-weight: 600;">Peak: {rpm_peak_str}</span>
                                <span style="opacity: 0.8;">Quota: {rpm_quota:.0f}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            """
        
        if not models_html:
            models_html = """
            <div style="
                text-align: center;
                padding: 40px;
                color: #9ca3af;
                font-size: 14px;
            ">No model usage detected in the selected time range</div>
            """
        
        # Build final HTML
        html = f"""
        <div style="
            padding: 12px;
            height: 100%;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
            background: #f9fafb;
            box-sizing: border-box;
            overflow-y: auto;
        ">
            {models_html}
        </div>
        """

        return html

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