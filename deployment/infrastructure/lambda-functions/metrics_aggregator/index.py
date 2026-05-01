# ABOUTME: Lambda function that aggregates Claude Code logs into CloudWatch Metrics
# ABOUTME: Runs every 5 minutes to pre-compute metrics for dashboard performance

import json
import boto3
import os
from datetime import datetime, timedelta, timezone
import time
from collections import defaultdict
from decimal import Decimal

# Initialize clients
logs_client = boto3.client("logs")
cloudwatch_client = boto3.client("cloudwatch")
dynamodb = boto3.resource("dynamodb")

# Configuration
NAMESPACE = "ClaudeCode"
LOG_GROUP = os.environ.get("METRICS_LOG_GROUP", "/aws/lambda/bedrock-claude-logs")
METRICS_TABLE = os.environ.get("METRICS_TABLE", "ClaudeCodeMetrics")
QUOTA_TABLE = os.environ.get("QUOTA_TABLE")  # Optional - only set if quota monitoring is enabled
POLICIES_TABLE = os.environ.get("POLICIES_TABLE")  # Optional - for fine-grained quotas
ENABLE_FINEGRAINED_QUOTAS = os.environ.get("ENABLE_FINEGRAINED_QUOTAS", "false").lower() == "true"
AGGREGATION_WINDOW = 5  # minutes
PRICING_REGION = os.environ.get("PRICING_REGION", "us-east-1")
PRICING_CACHE_FILE = "/tmp/bedrock_prices.json"
PRICING_CACHE_TTL = 7 * 86400  # 7 days

# Hardcoded fallback prices (per 1K tokens, USD) — used only if Pricing API
# has never been reached and no /tmp cache exists.
DEFAULT_PRICES = {
    "anthropic.claude-opus-4-6": {"input": 0.015, "output": 0.075, "cache_read": 0.01875},
    "anthropic.claude-opus-4-5": {"input": 0.015, "output": 0.075, "cache_read": 0.01875},
    "anthropic.claude-opus-4-1": {"input": 0.015, "output": 0.075, "cache_read": 0.01875},
    "anthropic.claude-opus-4": {"input": 0.015, "output": 0.075, "cache_read": 0.01875},
    "anthropic.claude-sonnet-4-6": {"input": 0.003, "output": 0.015, "cache_read": 0.003},
    "anthropic.claude-sonnet-4-5": {"input": 0.003, "output": 0.015, "cache_read": 0.003},
    "anthropic.claude-sonnet-4": {"input": 0.003, "output": 0.015, "cache_read": 0.003},
    "anthropic.claude-sonnet-3-7": {"input": 0.003, "output": 0.015, "cache_read": 0.003},
    "anthropic.claude-3-7-sonnet": {"input": 0.003, "output": 0.015, "cache_read": 0.003},
    "anthropic.claude-haiku-4-5": {"input": 0.0008, "output": 0.004, "cache_read": 0.0008},
    "anthropic.claude-3-5-haiku": {"input": 0.0008, "output": 0.004, "cache_read": 0.0008},
}
DEFAULT_PRICE_PER_1K = {"input": 0.003, "output": 0.015, "cache_read": 0.003}  # Sonnet-class fallback

# Module-level pricing cache — persists across warm Lambda invocations
_pricing_cache = None


def _match_model_prices(model_id, prices):
    """Look up pricing for a model ID, handling version suffixes and partial matches."""
    if not model_id or not prices:
        return DEFAULT_PRICE_PER_1K

    # Exact match
    if model_id in prices:
        return prices[model_id]

    # Strip version suffix (e.g. anthropic.claude-sonnet-4-20250514-v1:0 → anthropic.claude-sonnet-4)
    for key in prices:
        if model_id.startswith(key) or key.startswith(model_id):
            return prices[key]

    # Partial match on model family
    model_lower = model_id.lower()
    for key, val in prices.items():
        if key.lower() in model_lower or model_lower in key.lower():
            return val

    print(f"[WARN] No pricing found for model '{model_id}', using default")
    return DEFAULT_PRICE_PER_1K


def fetch_bedrock_prices(region):
    """Fetch Bedrock model prices from AWS Pricing API with /tmp file caching.

    Cache strategy:
    - Check /tmp/bedrock_prices.json (persists across warm invocations and
      some cold starts on the same execution environment)
    - If cache is valid (< 7 days old), return cached prices
    - Otherwise fetch from Pricing API, save to /tmp, return
    - On API failure: return stale cache or DEFAULT_PRICES
    """
    # Check /tmp cache
    try:
        if os.path.exists(PRICING_CACHE_FILE):
            with open(PRICING_CACHE_FILE) as f:
                cached = json.load(f)
            age = time.time() - cached.get("fetched_at", 0)
            if age < PRICING_CACHE_TTL:
                print(f"[INFO] Using cached pricing (age: {age/3600:.1f}h)")
                return cached["prices"]
            else:
                print(f"[INFO] Pricing cache expired (age: {age/86400:.1f}d), refreshing")
    except Exception as e:
        print(f"[WARN] Error reading pricing cache: {e}")

    # Fetch from Pricing API
    try:
        pricing_client = boto3.client("pricing", region_name="us-east-1")
        prices = {}
        next_token = None

        while True:
            params = {
                "ServiceCode": "AmazonBedrock",
                "Filters": [
                    {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
                    {"Type": "TERM_MATCH", "Field": "feature", "Value": "On-demand Inference"},
                ],
                "MaxResults": 100,
            }
            if next_token:
                params["NextToken"] = next_token

            response = pricing_client.get_products(**params)

            for price_json_str in response.get("PriceList", []):
                price_item = json.loads(price_json_str) if isinstance(price_json_str, str) else price_json_str
                attrs = price_item.get("product", {}).get("attributes", {})
                model_id = attrs.get("modelId", "")
                inference_type = attrs.get("inferenceType", "").lower()

                if not model_id:
                    continue

                # Extract price per 1K tokens
                for term_type in price_item.get("terms", {}).values():
                    for term in term_type.values():
                        for dim in term.get("priceDimensions", {}).values():
                            if dim.get("unit") == "1K tokens":
                                usd = float(dim.get("pricePerUnit", {}).get("USD", "0"))
                                if model_id not in prices:
                                    prices[model_id] = {}
                                if "input" in inference_type:
                                    prices[model_id]["input"] = usd
                                elif "output" in inference_type:
                                    prices[model_id]["output"] = usd
                                elif "cache" in inference_type and "read" in inference_type:
                                    prices[model_id]["cache_read"] = usd

            next_token = response.get("NextToken")
            if not next_token:
                break

        # Ensure all models have all price types
        for model_id in prices:
            prices[model_id].setdefault("input", DEFAULT_PRICE_PER_1K["input"])
            prices[model_id].setdefault("output", DEFAULT_PRICE_PER_1K["output"])
            prices[model_id].setdefault("cache_read", DEFAULT_PRICE_PER_1K["cache_read"])

        print(f"[INFO] Fetched pricing for {len(prices)} models from Pricing API")

        # Save to /tmp
        try:
            with open(PRICING_CACHE_FILE, "w") as f:
                json.dump({"prices": prices, "fetched_at": time.time()}, f)
        except Exception as e:
            print(f"[WARN] Failed to save pricing cache: {e}")

        return prices if prices else DEFAULT_PRICES

    except Exception as e:
        print(f"[WARN] Failed to fetch pricing from API: {e}")
        # Try stale cache
        try:
            if os.path.exists(PRICING_CACHE_FILE):
                with open(PRICING_CACHE_FILE) as f:
                    return json.load(f)["prices"]
        except Exception:
            pass
        print("[WARN] Using hardcoded default prices")
        return DEFAULT_PRICES


def get_model_prices():
    """Get model prices with in-memory caching (zero IO on warm invocations)."""
    global _pricing_cache
    if _pricing_cache is not None:
        return _pricing_cache
    region = os.environ.get("METRICS_REGION", PRICING_REGION)
    _pricing_cache = fetch_bedrock_prices(region)
    return _pricing_cache


def calculate_estimated_cost(input_tokens, output_tokens, cache_tokens, model):
    """Calculate estimated cost in USD for a set of token counts and model."""
    prices = get_model_prices()
    model_prices = _match_model_prices(model, prices)
    cost = (
        (input_tokens / 1000.0) * model_prices.get("input", DEFAULT_PRICE_PER_1K["input"])
        + (output_tokens / 1000.0) * model_prices.get("output", DEFAULT_PRICE_PER_1K["output"])
        + (cache_tokens / 1000.0) * model_prices.get("cache_read", DEFAULT_PRICE_PER_1K["cache_read"])
    )
    return round(cost, 6)


# DynamoDB tables
table = dynamodb.Table(METRICS_TABLE)
quota_table = dynamodb.Table(QUOTA_TABLE) if QUOTA_TABLE else None
policies_table = dynamodb.Table(POLICIES_TABLE) if POLICIES_TABLE else None


def lambda_handler(event, context):
    """
    Aggregate logs from the last 5 minutes and publish to CloudWatch Metrics.
    """
    print(f"Starting metrics aggregation for log group: {LOG_GROUP}")

    # Calculate time window
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=AGGREGATION_WINDOW)

    # Convert to milliseconds for CloudWatch Logs
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    try:
        # Collect all metrics
        metrics_to_publish = []

        # 1. Total Tokens
        total_tokens = aggregate_total_tokens(start_ms, end_ms)
        if total_tokens is not None:
            metrics_to_publish.append(
                {
                    "MetricName": "TotalTokens",
                    "Value": total_tokens,
                    "Unit": "Count",
                    "Timestamp": end_time,
                }
            )

        # 2. Active Users (now returns count and details)
        active_users_count, user_details = aggregate_active_users(start_ms, end_ms)
        if active_users_count is not None:
            metrics_to_publish.append(
                {
                    "MetricName": "ActiveUsers",
                    "Value": active_users_count,
                    "Unit": "Count",
                    "Timestamp": end_time,
                }
            )

        # 3. Lines of Code Added/Removed
        line_events, lines_added, lines_removed = aggregate_lines_of_code(
            start_ms, end_ms
        )

        # 3b. Model Rate Metrics (per-minute TPM/RPM)
        model_rate_metrics = aggregate_model_rate_metrics(start_ms, end_ms)

        # Write to DynamoDB
        write_to_dynamodb(
            end_time,
            total_tokens,
            active_users_count,
            user_details,
            lines_added,
            lines_removed,
            line_events,
            model_rate_metrics,
        )

        # Update quota tracking (only if quota monitoring is enabled)
        if quota_table:
            update_quota_table(end_time, user_details)
        else:
            print("Quota monitoring not enabled - skipping quota table updates")

        # Always publish lines metrics to CloudWatch (even if 0)
        metrics_to_publish.append(
            {
                "MetricName": "LinesAdded",
                "Value": lines_added,
                "Unit": "Count",
                "Timestamp": end_time,
            }
        )

        metrics_to_publish.append(
            {
                "MetricName": "LinesRemoved",
                "Value": lines_removed,
                "Unit": "Count",
                "Timestamp": end_time,
            }
        )

        # 4. Cache Metrics
        cache_metrics = aggregate_cache_metrics(start_ms, end_ms)
        for metric in cache_metrics:
            metrics_to_publish.append(metric)

        # 5. Top Users
        top_user_metrics = aggregate_top_users(start_ms, end_ms)
        for metric in top_user_metrics:
            metrics_to_publish.append(metric)

        # 6. Operations by Type
        operation_metrics = aggregate_operations(start_ms, end_ms)
        for metric in operation_metrics:
            metrics_to_publish.append(metric)

        # 7. Code Generation by Language
        language_metrics = aggregate_code_languages(start_ms, end_ms)
        for metric in language_metrics:
            metrics_to_publish.append(metric)

        # 8. Commits
        commit_count = aggregate_commits(start_ms, end_ms)
        if commit_count is not None:
            metrics_to_publish.append(
                {
                    "MetricName": "Commits",
                    "Value": commit_count,
                    "Unit": "Count",
                    "Timestamp": end_time,
                }
            )

        # Publish metrics in batches (max 20 per request)
        for i in range(0, len(metrics_to_publish), 20):
            batch = metrics_to_publish[i : i + 20]
            cloudwatch_client.put_metric_data(Namespace=NAMESPACE, MetricData=batch)
            print(f"Published {len(batch)} metrics to CloudWatch")

        print(
            f"Successfully aggregated and published {len(metrics_to_publish)} metrics"
        )
        return {
            "statusCode": 200,
            "body": json.dumps(f"Published {len(metrics_to_publish)} metrics"),
        }

    except Exception as e:
        print(f"Error during aggregation: {str(e)}")
        return {"statusCode": 500, "body": json.dumps(f"Error: {str(e)}")}


def run_query(query, start_ms, end_ms):
    """
    Run a CloudWatch Logs Insights query and wait for results.
    """
    try:
        response = logs_client.start_query(
            logGroupName=LOG_GROUP,
            startTime=start_ms,
            endTime=end_ms,
            queryString=query,
        )

        query_id = response["queryId"]

        # Wait for query to complete (max 30 seconds)
        for _ in range(30):
            response = logs_client.get_query_results(queryId=query_id)
            status = response["status"]

            if status == "Complete":
                return response.get("results", [])
            elif status in ["Failed", "Cancelled"]:
                print(f"Query failed with status: {status}")
                return []

            time.sleep(1)

        print("Query timed out")
        return []

    except Exception as e:
        print(f"Error running query: {str(e)}")
        return []


def aggregate_total_tokens(start_ms, end_ms):
    """
    Aggregate total token usage.
    """
    query = """
    fields @message
    | filter @message like /claude_code.token.usage/
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | stats sum(tokens) as total_tokens
    """

    results = run_query(query, start_ms, end_ms)
    if results and len(results) > 0:
        for field in results[0]:
            if field["field"] == "total_tokens":
                return float(field["value"])
    return 0


def aggregate_active_users(start_ms, end_ms):
    """
    Count distinct active users and return user details with token type breakdown.
    Also extracts JWT group claims for fine-grained quota support.
    """
    # First get unique count for CloudWatch metric
    query_count = """
    fields @message
    | filter @message like /user.email/
    | parse @message /"user.email":"(?<user>[^"]*)"/
    | stats count_distinct(user) as active_users
    """

    unique_count = 0
    results = run_query(query_count, start_ms, end_ms)
    if results and len(results) > 0:
        for field in results[0]:
            if field["field"] == "active_users":
                unique_count = int(float(field["value"]))

    # Get user details with token type breakdown for cost calculation
    # This query extracts input, output, and cache tokens separately
    query_details = """
    fields @message
    | filter @message like /user.email/
    | parse @message /"user.email":"(?<user>[^"]*)"/
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | parse @message /"type":"(?<token_type>[^"]*)"/
    | parse @message /"model":"(?<model>[^"]*)"/
    | stats sum(tokens) as total_tokens, count() as requests by user, token_type, model
    | sort user asc
    """

    # Aggregate by user, collecting token types
    user_data = {}
    results = run_query(query_details, start_ms, end_ms)
    for result in results:
        user_email = None
        tokens = 0
        requests = 0
        token_type = None
        model = None

        for field in result:
            if field["field"] == "user":
                user_email = field["value"]
            elif field["field"] == "total_tokens":
                tokens = float(field["value"])
            elif field["field"] == "requests":
                requests = int(float(field["value"]))
            elif field["field"] == "token_type":
                token_type = field["value"]
            elif field["field"] == "model":
                model = field["value"]

        if user_email:
            if user_email not in user_data:
                user_data[user_email] = {
                    "email": user_email,
                    "tokens": 0,
                    "requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_tokens": 0,
                    "model": model,  # Track last model used
                }

            user_data[user_email]["tokens"] += tokens

            # Track token types for cost calculation
            if token_type == "input":
                user_data[user_email]["input_tokens"] += tokens
                user_data[user_email]["requests"] += requests  # Count requests only for input
            elif token_type == "output":
                user_data[user_email]["output_tokens"] += tokens
            elif token_type in ("cacheRead", "cache_read"):
                user_data[user_email]["cache_tokens"] += tokens

            # Keep track of model (use latest)
            if model:
                user_data[user_email]["model"] = model

    # Query for JWT group claims (groups, cognito:groups, custom:department)
    if ENABLE_FINEGRAINED_QUOTAS:
        query_groups = """
        fields @message
        | filter @message like /user.email/
        | parse @message /"user.email":"(?<user>[^"]*)"/
        | parse @message /"groups":\[(?<groups>[^\]]*)\]/
        | parse @message /"cognito:groups":\[(?<cognito_groups>[^\]]*)\]/
        | parse @message /"custom:department":"(?<department>[^"]*)"/
        | stats latest(groups) as groups, latest(cognito_groups) as cognito_groups, latest(department) as department by user
        """

        results = run_query(query_groups, start_ms, end_ms)
        for result in results:
            user_email = None
            groups_str = None
            cognito_groups_str = None
            department = None

            for field in result:
                if field["field"] == "user":
                    user_email = field["value"]
                elif field["field"] == "groups":
                    groups_str = field["value"]
                elif field["field"] == "cognito_groups":
                    cognito_groups_str = field["value"]
                elif field["field"] == "department":
                    department = field["value"]

            if user_email and user_email in user_data:
                # Parse and combine all group sources
                all_groups = set()

                # Parse groups array (format: "group1","group2")
                if groups_str:
                    for g in groups_str.replace('"', '').split(','):
                        g = g.strip()
                        if g:
                            all_groups.add(g)

                # Parse cognito:groups array
                if cognito_groups_str:
                    for g in cognito_groups_str.replace('"', '').split(','):
                        g = g.strip()
                        if g:
                            all_groups.add(g)

                # Add department as a group
                if department:
                    all_groups.add(department)

                user_data[user_email]["groups"] = list(all_groups)

    # Convert to list and sort by tokens
    user_details = sorted(user_data.values(), key=lambda x: x["tokens"], reverse=True)

    return unique_count, user_details


def aggregate_cache_metrics(start_ms, end_ms):
    """
    Aggregate cache hit/miss metrics and token type metrics.
    """
    metrics = []
    timestamp = datetime.now(timezone.utc)

    # Query for all token types including input, output, cache
    query = """
    fields @message
    | filter @message like /claude_code.token.usage/
    | parse @message /"type":"(?<token_type>[^"]*)"/
    | filter token_type in ["input", "output", "cacheRead", "cacheCreation"]
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | stats sum(tokens) as total by token_type
    """

    results = run_query(query, start_ms, end_ms)

    for result in results:
        token_type = None
        total = 0
        for field in result:
            if field["field"] == "token_type":
                token_type = field["value"]
            elif field["field"] == "total":
                total = float(field["value"])

        if token_type and total > 0:
            # Map token types to metric names
            if token_type == "input":
                metrics.append(
                    {
                        "MetricName": "InputTokens",
                        "Value": total,
                        "Unit": "Count",
                        "Timestamp": timestamp,
                    }
                )
            elif token_type == "output":
                metrics.append(
                    {
                        "MetricName": "OutputTokens",
                        "Value": total,
                        "Unit": "Count",
                        "Timestamp": timestamp,
                    }
                )
            elif token_type == "cacheRead":
                metrics.append(
                    {
                        "MetricName": "CacheReadTokens",
                        "Value": total,
                        "Unit": "Count",
                        "Timestamp": timestamp,
                    }
                )
            elif token_type == "cacheCreation":
                metrics.append(
                    {
                        "MetricName": "CacheCreationTokens",
                        "Value": total,
                        "Unit": "Count",
                        "Timestamp": timestamp,
                    }
                )

    # Calculate cache efficiency if we have cache metrics
    cache_read_tokens = 0
    cache_creation_tokens = 0
    for metric in metrics:
        if metric["MetricName"] == "CacheReadTokens":
            cache_read_tokens = metric["Value"]
        elif metric["MetricName"] == "CacheCreationTokens":
            cache_creation_tokens = metric["Value"]

    total_cache = cache_read_tokens + cache_creation_tokens
    if total_cache > 0:
        efficiency = (cache_read_tokens / total_cache) * 100
        metrics.append(
            {
                "MetricName": "CacheEfficiency",
                "Value": efficiency,
                "Unit": "Percent",
                "Timestamp": timestamp,
            }
        )

    return metrics


def aggregate_top_users(start_ms, end_ms):
    """
    Aggregate top 10 users by token usage.
    """
    metrics = []
    timestamp = datetime.now(timezone.utc)

    query = """
    fields @message
    | filter @message like /user.email/
    | parse @message /"user.email":"(?<user>[^"]*)"/
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | stats sum(tokens) as total_tokens by user
    | sort total_tokens desc
    | limit 10
    """

    results = run_query(query, start_ms, end_ms)

    for rank, result in enumerate(results, 1):
        user = None
        tokens = 0
        for field in result:
            if field["field"] == "user":
                user = field["value"]
            elif field["field"] == "total_tokens":
                tokens = float(field["value"])

        if user and tokens > 0:
            # Store as ranked metric
            metrics.append(
                {
                    "MetricName": "TopUserTokens",
                    "Dimensions": [
                        {"Name": "Rank", "Value": str(rank)},
                        {"Name": "User", "Value": user},
                    ],
                    "Value": tokens,
                    "Unit": "Count",
                    "Timestamp": timestamp,
                }
            )

    return metrics


def aggregate_operations(start_ms, end_ms):
    """
    Aggregate operations by type.
    """
    metrics = []
    timestamp = datetime.now(timezone.utc)

    query = """
    fields @message
    | filter @message like /tool_name/
    | parse @message /"tool_name":"(?<tool>[^"]*)"/
    | stats count() as usage by tool
    """

    results = run_query(query, start_ms, end_ms)

    for result in results:
        tool = None
        usage = 0
        for field in result:
            if field["field"] == "tool":
                tool = field["value"]
            elif field["field"] == "usage":
                usage = float(field["value"])

        if tool and usage > 0:
            metrics.append(
                {
                    "MetricName": "OperationCount",
                    "Dimensions": [{"Name": "OperationType", "Value": tool}],
                    "Value": usage,
                    "Unit": "Count",
                    "Timestamp": timestamp,
                }
            )

    return metrics


def aggregate_code_languages(start_ms, end_ms):
    """
    Aggregate code generation by language.
    """
    metrics = []
    timestamp = datetime.now(timezone.utc)

    query = """
    fields @message
    | filter @message like /code_edit_tool.decision/
    | parse @message /"language":"(?<lang>[^"]*)"/
    | stats count() as edits by lang
    """

    results = run_query(query, start_ms, end_ms)

    for result in results:
        lang = None
        edits = 0
        for field in result:
            if field["field"] == "lang":
                lang = field["value"]
            elif field["field"] == "edits":
                edits = float(field["value"])

        if lang and edits > 0:
            metrics.append(
                {
                    "MetricName": "CodeEditsByLanguage",
                    "Dimensions": [{"Name": "Language", "Value": lang}],
                    "Value": edits,
                    "Unit": "Count",
                    "Timestamp": timestamp,
                }
            )

    return metrics


def aggregate_commits(start_ms, end_ms):
    """
    Aggregate commit count.
    """
    query = """
    fields @message
    | filter @message like /claude_code.commit.count/
    | stats count() as total_commits
    """

    results = run_query(query, start_ms, end_ms)
    if results and len(results) > 0:
        for field in results[0]:
            if field["field"] == "total_commits":
                return int(float(field["value"]))
    return 0


def aggregate_lines_of_code(start_ms, end_ms):
    """
    Get individual line change events (not aggregated).
    Returns list of events with timestamp, type, and count.
    """
    query = """
    fields @timestamp, @message
    | filter @message like /claude_code.lines_of_code.count/
    | parse @message /"type":"(?<type>[^"]*)"/
    | parse @message /"claude_code.lines_of_code.count":(?<lines>[0-9.]+)/
    | sort @timestamp asc
    """

    events = []
    lines_added_total = 0
    lines_removed_total = 0

    results = run_query(query, start_ms, end_ms)
    for result in results:
        timestamp = None
        line_type = None
        lines = 0

        for field in result:
            if field["field"] == "@timestamp":
                timestamp = field["value"]
            elif field["field"] == "type":
                line_type = field["value"].lower()
            elif field["field"] == "lines":
                lines = float(field["value"])

        if timestamp and line_type and lines >= 0:
            events.append({"timestamp": timestamp, "type": line_type, "count": lines})

            if line_type == "added":
                lines_added_total += lines
            elif line_type == "removed":
                lines_removed_total += lines

    return events, lines_added_total, lines_removed_total


def aggregate_model_rate_metrics(start_ms, end_ms):
    """
    Query logs and bucket token/request counts by model and minute.
    Returns dict of model -> minute -> {tokens, requests} for DynamoDB storage.
    """
    # Query for all token usage with timestamps and models
    query = """
    fields @timestamp, @message
    | filter @message like /claude_code.token.usage/
    | parse @message /"model":"(?<model>[^"]*)"/
    | parse @message /"claude_code.token.usage":(?<tokens>[0-9.]+)/
    | parse @message /"type":"(?<token_type>[^"]*)"/
    | sort @timestamp asc
    """

    model_metrics = defaultdict(
        lambda: defaultdict(lambda: {"tokens": 0, "requests": 0})
    )

    results = run_query(query, start_ms, end_ms)
    for result in results:
        timestamp = None
        model = None
        tokens = 0
        token_type = None

        for field in result:
            if field["field"] == "@timestamp":
                timestamp = field["value"]
            elif field["field"] == "model":
                model = field["value"]
            elif field["field"] == "tokens":
                tokens = float(field["value"])
            elif field["field"] == "token_type":
                token_type = field["value"]

        if timestamp and model and tokens > 0:
            # Parse timestamp and bucket by minute
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                # Round down to minute
                minute_dt = dt.replace(second=0, microsecond=0)
                minute_str = minute_dt.strftime("%H:%M:%S")

                # Add tokens to the minute bucket for this model
                model_metrics[model][minute_str]["tokens"] += tokens

                # Count requests (only for input tokens to avoid double counting)
                if token_type == "input":
                    model_metrics[model][minute_str]["requests"] += 1
            except Exception as e:
                print(f"Error parsing timestamp {timestamp}: {str(e)}")

    return model_metrics


def write_to_dynamodb(
    timestamp,
    total_tokens,
    unique_users,
    user_details,
    lines_added,
    lines_removed,
    line_events=None,
    model_rate_metrics=None,
):
    """
    Write aggregated metrics to DynamoDB using single-partition design.
    Schema: PK=METRICS, SK=ISO_TIMESTAMP#TYPE#DETAIL
    Stores window summaries, user metrics, line events, and per-model rate metrics.
    """
    try:
        # Format timestamps
        iso_timestamp = timestamp.isoformat().replace("+00:00", "Z")
        ttl = int((timestamp + timedelta(days=30)).timestamp())  # 30 day retention

        # Convert user details to Decimal
        top_users_decimal = []
        for user in user_details[:10] if user_details else []:
            top_users_decimal.append(
                {
                    "email": user["email"],
                    "tokens": Decimal(str(user.get("tokens", 0))),
                    "requests": Decimal(str(user.get("requests", 0))),
                }
            )

        with table.batch_writer() as batch:
            # 1. Write 5-minute window aggregate
            window_item = {
                "pk": "METRICS",
                "sk": f"{iso_timestamp}#WINDOW#SUMMARY",
                "unique_users": unique_users,
                "total_tokens": (
                    Decimal(str(total_tokens)) if total_tokens else Decimal(0)
                ),
                "top_users": top_users_decimal,
                "lines_added": Decimal(str(lines_added)) if lines_added else Decimal(0),
                "lines_removed": (
                    Decimal(str(lines_removed)) if lines_removed else Decimal(0)
                ),
                "timestamp": iso_timestamp,
                "ttl": ttl,
            }
            batch.put_item(Item=window_item)

            # 2. Write lines of code summary
            if lines_added > 0 or lines_removed > 0:
                lines_item = {
                    "pk": "METRICS",
                    "sk": f"{iso_timestamp}#LINES#SUMMARY",
                    "lines_added": Decimal(str(lines_added)),
                    "lines_removed": Decimal(str(lines_removed)),
                    "timestamp": iso_timestamp,
                    "ttl": ttl,
                }
                batch.put_item(Item=lines_item)

            # 2b. Write individual line change events
            if line_events:
                for event in line_events:
                    # Parse event timestamp to get ISO format
                    event_dt = datetime.fromisoformat(
                        event["timestamp"].replace("Z", "+00:00")
                    )
                    event_iso = event_dt.isoformat() + "Z"

                    # Use timestamp + type as unique identifier
                    event_id = f"{event['type'].upper()}#{event_dt.timestamp()}"

                    line_event_item = {
                        "pk": "METRICS",
                        "sk": f"{event_iso}#LINES#EVENT#{event_id}",
                        "type": event["type"],
                        "count": Decimal(str(event["count"])),
                        "timestamp": event_iso,
                        "ttl": ttl,
                    }
                    batch.put_item(Item=line_event_item)

            # 3. Write individual user metrics for this window
            for user in user_details:
                # Calculate estimated cost using dynamic pricing
                est_cost = calculate_estimated_cost(
                    float(user.get("input_tokens", 0)),
                    float(user.get("output_tokens", 0)),
                    float(user.get("cache_tokens", 0)),
                    user.get("model", ""),
                )
                user_item = {
                    "pk": "METRICS",
                    "sk": f'{iso_timestamp}#USER#{user["email"]}',
                    "tokens": Decimal(str(user.get("tokens", 0))),
                    "requests": Decimal(str(user.get("requests", 0))),
                    "estimated_cost": Decimal(str(est_cost)),
                    "email": user["email"],
                    "timestamp": iso_timestamp,
                    "ttl": ttl,
                }
                batch.put_item(Item=user_item)

            # 4. Write per-model, per-minute rate metrics
            if model_rate_metrics:
                for model_id, minute_data in model_rate_metrics.items():
                    for minute_time, metrics in minute_data.items():
                        # Parse the minute time to get the full timestamp
                        # minute_time is in format HH:MM:SS, combine with date from main timestamp
                        minute_dt = datetime.combine(
                            timestamp.date(),
                            datetime.strptime(minute_time, "%H:%M:%S").time(),
                            tzinfo=timezone.utc,
                        )
                        minute_iso = minute_dt.isoformat().replace("+00:00", "Z")

                        model_rate_item = {
                            "pk": "METRICS",
                            "sk": f"{minute_iso}#MODEL_RATE#{model_id}",
                            "model": model_id,
                            "tpm": Decimal(str(metrics["tokens"])),
                            "rpm": Decimal(str(metrics["requests"])),
                            "timestamp": minute_iso,
                            "ttl": ttl,
                        }
                        batch.put_item(Item=model_rate_item)

        line_events_count = len(line_events) if line_events else 0
        model_rate_count = (
            sum(len(minutes) for minutes in model_rate_metrics.values())
            if model_rate_metrics
            else 0
        )
        print(
            f"Wrote window summary, {line_events_count} line events, {model_rate_count} model rate metrics, and {len(user_details)} user records to DynamoDB"
        )

    except Exception as e:
        print(f"Error writing to DynamoDB: {str(e)}")


def update_quota_table(timestamp, user_details):
    """
    Update monthly user quota tracking table with enhanced fields.
    Schema: PK=USER#{email}, SK=MONTH#{YYYY-MM}
    Maintains running totals for each user per month including:
    - Monthly and daily token totals
    - Token type breakdown (input, output, cache)
    - Group membership from JWT claims
    """
    if not user_details:
        return

    try:
        current_month = timestamp.strftime("%Y-%m")
        current_date = timestamp.strftime("%Y-%m-%d")
        ttl = int(
            (timestamp.replace(day=28) + timedelta(days=32)).replace(day=1).timestamp()
        )  # End of next month

        for user in user_details:
            user_email = user["email"]
            tokens_to_add = float(user.get("tokens", 0))
            input_tokens = float(user.get("input_tokens", 0))
            output_tokens = float(user.get("output_tokens", 0))
            cache_tokens = float(user.get("cache_tokens", 0))
            groups = user.get("groups", [])

            if tokens_to_add <= 0:
                continue

            pk = f"USER#{user_email}"
            sk = f"MONTH#{current_month}"

            # First, get the current record to check daily_date
            try:
                response = quota_table.get_item(Key={"pk": pk, "sk": sk})
                existing = response.get("Item", {})
                existing_daily_date = existing.get("daily_date")

                # Determine if we need to reset daily tokens
                if existing_daily_date != current_date:
                    # New day - reset daily tokens
                    daily_tokens_expr = ":tokens"
                    daily_reset = True
                else:
                    # Same day - add to existing
                    daily_tokens_expr = "daily_tokens + :tokens"
                    daily_reset = False

                # Build update expression with all enhanced fields
                update_expr = """
                    ADD total_tokens :tokens,
                        input_tokens :input_tokens,
                        output_tokens :output_tokens,
                        cache_tokens :cache_tokens
                    SET last_updated = :updated,
                        #ttl = :ttl,
                        email = :email,
                        daily_date = :daily_date
                """

                expr_attr_values = {
                    ":tokens": Decimal(str(tokens_to_add)),
                    ":input_tokens": Decimal(str(input_tokens)),
                    ":output_tokens": Decimal(str(output_tokens)),
                    ":cache_tokens": Decimal(str(cache_tokens)),
                    ":updated": timestamp.isoformat().replace("+00:00", "Z"),
                    ":ttl": ttl,
                    ":email": user_email,
                    ":daily_date": current_date,
                }

                expr_attr_names = {"#ttl": "ttl"}

                # Handle daily tokens based on date change
                if daily_reset:
                    update_expr += ", daily_tokens = :tokens"
                else:
                    update_expr = update_expr.replace(
                        "ADD total_tokens :tokens",
                        "ADD total_tokens :tokens, daily_tokens :tokens"
                    )

                # Add groups if available (for fine-grained quotas)
                if groups and ENABLE_FINEGRAINED_QUOTAS:
                    update_expr += ", #groups = :groups"
                    expr_attr_values[":groups"] = groups
                    expr_attr_names["#groups"] = "groups"

                quota_table.update_item(
                    Key={"pk": pk, "sk": sk},
                    UpdateExpression=update_expr,
                    ExpressionAttributeNames=expr_attr_names,
                    ExpressionAttributeValues=expr_attr_values,
                )

                daily_note = " (daily reset)" if daily_reset else ""
                print(
                    f"Updated quota for {user_email}: +{tokens_to_add:,.0f} tokens for {current_month}{daily_note}"
                )

            except Exception as e:
                print(f"Error updating quota for {user_email}: {str(e)}")

    except Exception as e:
        print(f"Error in update_quota_table: {str(e)}")
