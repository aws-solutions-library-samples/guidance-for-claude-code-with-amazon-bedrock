# ABOUTME: Lambda function that bridges Bedrock inference profile metrics to OTEL log format
# ABOUTME: Reads InputTokenCount/OutputTokenCount/CacheRead/CacheWrite from AWS/Bedrock
# ABOUTME: CloudWatch namespace per InferenceProfileArn, maps ARN to user email via tags,
# ABOUTME: then writes structured JSON log records to /aws/claude-code/metrics in exactly
# ABOUTME: the same format the ADOT awsemf exporter would produce.
# ABOUTME: This lets the metrics aggregator, widget Lambdas, and quota checks all work
# ABOUTME: unchanged when inference profiles are used instead of the OTEL collector.

import json
import boto3
import os
from datetime import datetime, timedelta, timezone

# Clients
cloudwatch_client = boto3.client("cloudwatch")
bedrock_client = boto3.client("bedrock")
logs_client = boto3.client("logs")
boto3_session = boto3.session.Session()

# Configuration
LOG_GROUP = os.environ.get("METRICS_LOG_GROUP", "/aws/claude-code/metrics")
LOG_STREAM = "bedrock-metrics-bridge"
AGGREGATION_WINDOW = 5    # minutes — must match the EventBridge schedule rate
METRIC_PERIOD = 300       # seconds — granularity of AWS/Bedrock datapoints (5 min)
# Query slightly more than one period back to absorb CloudWatch ingestion delay
# (~1-2 min) without double-counting: we ask for exactly one METRIC_PERIOD window
# ending 2 minutes ago so the datapoint has had time to be ingested.
INGESTION_DELAY = 2       # minutes


def lambda_handler(event, context):
    print(f"Starting Bedrock metrics bridge → {LOG_GROUP}")

    # Shift the window back by INGESTION_DELAY to ensure the most recent
    # 5-minute Bedrock datapoint has been ingested before we query it.
    end_time = datetime.now(timezone.utc) - timedelta(minutes=INGESTION_DELAY)
    start_time = end_time - timedelta(minutes=AGGREGATION_WINDOW)

    # 1. Build ARN → { email, model } map
    arn_to_profile = _build_arn_to_profile_map()
    if not arn_to_profile:
        print("No inference profiles with email tags found — nothing to bridge")
        return {"statusCode": 200, "body": "No inference profiles found"}

    print(f"Found {len(arn_to_profile)} inference profile(s)")

    # 2. Fetch token counts from AWS/Bedrock namespace
    bedrock_metrics = _get_bedrock_metrics(list(arn_to_profile.keys()), start_time, end_time)

    # 3. Ensure log group and stream exist
    _ensure_log_stream(LOG_GROUP, LOG_STREAM)

    # 4. Build log events in OTEL/awsemf format and put them
    log_events = _build_log_events(arn_to_profile, bedrock_metrics, end_time)
    if log_events:
        _put_log_events(LOG_GROUP, LOG_STREAM, log_events)
        print(f"Published {len(log_events)} log event(s) to {LOG_GROUP}")
    else:
        print("No token activity in this window — no log events written")

    return {"statusCode": 200, "body": json.dumps(f"Published {len(log_events)} log events")}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_arn_to_profile_map() -> dict:
    """
    Return { inferenceProfileArn: { "email": str, "model": str } } for all
    APPLICATION profiles tagged with 'user.email'.
    Model name is extracted from the underlying model source ARN
    (e.g. arn:...:foundation-model/anthropic.claude-sonnet-4-5-... → claude-sonnet-4-5).
    """
    result = {}
    try:
        paginator = bedrock_client.get_paginator("list_inference_profiles")
        for page in paginator.paginate(typeEquals="APPLICATION"):
            for summary in page.get("inferenceProfileSummaries", []):
                arn = summary.get("inferenceProfileArn")
                if not arn:
                    continue

                email = None
                model = "unknown"

                # Get email tag
                try:
                    tags = bedrock_client.list_tags_for_resource(resourceARN=arn).get("tags", [])
                    for tag in tags:
                        if tag.get("key") == "user.email":
                            email = tag["value"]
                            break
                except Exception as e:
                    print(f"Warning: could not get tags for {arn}: {e}")

                if not email:
                    continue  # skip profiles without email tag

                # Get model name from modelSources via get_inference_profile
                try:
                    detail = bedrock_client.get_inference_profile(inferenceProfileIdentifier=arn)
                    print(f"  get_inference_profile response keys: {list(detail.keys())}")
                    sources = detail.get("models", [])
                    print(f"  models ({len(sources)}): {sources}")
                    if sources:
                        model_arn = sources[0].get("modelArn", "")
                        print(f"  modelArn: {model_arn}")
                        model = _model_name_from_model_arn(model_arn)
                        print(f"  resolved model: {model}")
                except Exception as e:
                    print(f"Warning: could not get model source for {arn}: {e}")

                result[arn] = {"email": email, "model": model}
                print(f"  Profile {arn.split('/')[-1]}: email={email}, model={model}")

    except Exception as e:
        print(f"Error listing inference profiles: {e}")
    return result


def _model_name_from_model_arn(model_arn: str) -> str:
    """
    Extract a friendly model name from a foundation model ARN.
    e.g. arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0
    → claude-sonnet-4-5
    """
    import re
    try:
        print(f"  parsing model_arn: '{model_arn}'")
        # Get the part after the last '/'
        model_id = model_arn.split("/")[-1]  # e.g. anthropic.claude-sonnet-4-5-20250929-v1:0
        print(f"  after split('/'): '{model_id}'")
        # Strip provider prefix (e.g. anthropic.)
        model_id = model_id.split(".")[-1] if "." in model_id else model_id
        print(f"  after strip prefix: '{model_id}'")
        # Strip version suffix (e.g. -v1:0 or -v2:0)
        for suffix_pattern in ["-v1:0", "-v2:0", "-v1", "-v2"]:
            if suffix_pattern in model_id:
                model_id = model_id[:model_id.rfind(suffix_pattern)]
                break
        print(f"  after strip version: '{model_id}'")
        # Strip date stamp (8-digit sequence like -20250929)
        model_id = re.sub(r"-\d{8}$", "", model_id)
        print(f"  final model_id: '{model_id}'")
        return model_id
    except Exception as e:
        print(f"  _model_name_from_model_arn error: {e}")
        return "unknown"


def _get_bedrock_metrics(profile_arns: list, start_time: datetime, end_time: datetime) -> dict:
    """
    Fetch token counts from AWS/Bedrock namespace for each profile ARN.
    Returns { arn: { "input": N, "output": N, "cache_read": N, "cache_write": N } }
    """
    metric_names = [
        ("InputTokenCount",           "input"),
        ("OutputTokenCount",          "output"),
        ("CacheReadInputTokenCount",  "cache_read"),
        ("CacheWriteInputTokenCount", "cache_write"),
    ]

    queries = []
    index = {}  # query id → (arn, key)
    for i, arn in enumerate(profile_arns):
        # AWS/Bedrock metrics use ModelId dimension with the profile's short ID
        # e.g. arn:.../application-inference-profile/82ey7vcct4m3 → "82ey7vcct4m3"
        profile_id = arn.split("/")[-1]
        for cw_name, key in metric_names:
            qid = f"q{i}_{key}"
            queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/Bedrock",
                        "MetricName": cw_name,
                        "Dimensions": [{"Name": "ModelId", "Value": profile_id}],
                    },
                    "Period": METRIC_PERIOD,
                    "Stat": "Sum",
                },
                "ReturnData": True,
            })
            index[qid] = (arn, key)

    results = {arn: {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0}
               for arn in profile_arns}

    # get_metric_data max 500 queries per call
    for batch_start in range(0, len(queries), 500):
        batch = queries[batch_start:batch_start + 500]
        try:
            response = cloudwatch_client.get_metric_data(
                MetricDataQueries=batch,
                StartTime=start_time,
                EndTime=end_time,
            )
            for r in response.get("MetricDataResults", []):
                values = r.get("Values", [])
                qid = r["Id"]
                if qid in index:
                    arn, key = index[qid]
                    if values:
                        total = sum(values)
                        results[arn][key] += total
                        print(f"  {qid}: {len(values)} datapoint(s), total={total:.0f}")
                    else:
                        print(f"  {qid}: no datapoints")
        except Exception as e:
            print(f"Error fetching Bedrock metrics: {e}")

    # Log summary
    active = {arn: v for arn, v in results.items() if any(v.values())}
    print(f"Active ARNs with data: {len(active)}/{len(profile_arns)}")

    return results


def _build_log_events(arn_to_profile: dict, bedrock_metrics: dict, timestamp: datetime) -> list:
    """
    Produce one CloudWatch Logs event per (user, token_type) combination, in the
    same JSON structure the ADOT awsemf exporter writes.
    """
    ts_ms = int(timestamp.timestamp() * 1000)
    events = []

    type_map = [
        ("input",       "input"),
        ("output",      "output"),
        ("cache_read",  "cacheRead"),
        ("cache_write", "cacheCreation"),
    ]

    for arn, counts in bedrock_metrics.items():
        profile = arn_to_profile.get(arn)
        if not profile:
            continue

        email = profile["email"]
        model = profile["model"]

        for metric_key, otel_type in type_map:
            count = counts.get(metric_key, 0.0)
            if count <= 0:
                continue

            record = {
                "_aws": {
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "ClaudeCode",
                            "Dimensions": [
                                ["type"],
                                ["model"],
                                ["user.email"],
                                ["type", "model"],
                                ["type", "user.email"],
                            ],
                            "Metrics": [
                                {"Name": "claude_code.token.usage", "Unit": "Count"},
                            ],
                        }
                    ],
                    "Timestamp": ts_ms,
                },
                "user.email": email,
                "claude_code.token.usage": count,
                "type": otel_type,
                "model": model,
                "OTelLib": "claude_code",
            }
            events.append({
                "timestamp": ts_ms,
                "message": json.dumps(record, separators=(',', ':')),
            })

    return events


def _ensure_log_stream(log_group: str, log_stream: str) -> None:
    """Create the log group and stream if they do not already exist."""
    try:
        logs_client.create_log_group(logGroupName=log_group)
        print(f"Created log group {log_group}")
    except logs_client.exceptions.ResourceAlreadyExistsException:
        pass
    except Exception as e:
        print(f"Warning: could not create log group {log_group}: {e}")

    try:
        logs_client.create_log_stream(logGroupName=log_group, logStreamName=log_stream)
        print(f"Created log stream {log_stream}")
    except logs_client.exceptions.ResourceAlreadyExistsException:
        pass
    except Exception as e:
        print(f"Warning: could not create log stream {log_stream}: {e}")


def _put_log_events(log_group: str, log_stream: str, events: list) -> None:
    """Write events to CloudWatch Logs, batching if needed (max 10 000 / 1 MB per call)."""
    # Sort by timestamp (required by PutLogEvents)
    events = sorted(events, key=lambda e: e["timestamp"])

    batch_size = 500  # well within the 10 000 event and 1 MB limits
    for i in range(0, len(events), batch_size):
        batch = events[i:i + batch_size]
        try:
            logs_client.put_log_events(
                logGroupName=log_group,
                logStreamName=log_stream,
                logEvents=batch,
            )
        except Exception as e:
            print(f"Error putting log events (batch {i}): {e}")
