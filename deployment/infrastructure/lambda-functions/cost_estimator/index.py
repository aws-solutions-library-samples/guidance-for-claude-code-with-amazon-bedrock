"""
Cost Estimator Lambda — computes per-model token cost from CloudWatch metrics.

Runs hourly via EventBridge. Reads claude_code.token.usage metrics from CloudWatch,
looks up per-model pricing from AWS Pricing API (cached), and publishes
claude_code.cost.estimated metrics back to CloudWatch.

Works with both central and sidecar collector modes — reads from the common
CloudWatch namespace regardless of how metrics were ingested.
"""

import json
import os
import time
from datetime import datetime, timedelta

import boto3

# CloudWatch namespace for Claude Code metrics
NAMESPACE = os.environ.get("METRICS_NAMESPACE", "ClaudeCode")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Pricing cache (in-memory for warm invocations, /tmp for cold starts)
_pricing_cache = {"prices": None, "fetched_at": 0}
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
CACHE_FILE = "/tmp/bedrock_prices.json"

# Fallback prices per 1M tokens (USD) — used when Pricing API is unavailable
DEFAULT_PRICES = {
    "opus": {"input": 15.00, "output": 75.00, "cacheRead": 1.50, "cacheCreation": 18.75},
    "sonnet": {"input": 3.00, "output": 15.00, "cacheRead": 0.30, "cacheCreation": 3.75},
    "haiku": {"input": 0.80, "output": 4.00, "cacheRead": 0.08, "cacheCreation": 1.00},
}


def get_model_family(model_id: str) -> str:
    """Extract model family from a CRIS model ID."""
    model_lower = model_id.lower()
    if "opus" in model_lower:
        return "opus"
    elif "haiku" in model_lower:
        return "haiku"
    else:
        return "sonnet"


def fetch_bedrock_prices() -> dict:
    """Fetch per-model pricing from AWS Pricing API with caching.

    Returns dict: {family: {input: price_per_1M, output: price_per_1M, ...}}
    Falls back to DEFAULT_PRICES on failure.
    """
    now = time.time()

    # Check in-memory cache
    if _pricing_cache["prices"] and (now - _pricing_cache["fetched_at"]) < CACHE_TTL_SECONDS:
        return _pricing_cache["prices"]

    # Check /tmp file cache
    try:
        with open(CACHE_FILE, "r") as f:
            cached = json.load(f)
            if (now - cached.get("fetched_at", 0)) < CACHE_TTL_SECONDS:
                _pricing_cache["prices"] = cached["prices"]
                _pricing_cache["fetched_at"] = cached["fetched_at"]
                return cached["prices"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    # Fetch from Pricing API
    try:
        pricing = boto3.client("pricing", region_name="us-east-1")
        prices = {}

        for family in ["opus", "sonnet", "haiku"]:
            # Query Bedrock pricing for Anthropic Claude models
            response = pricing.get_products(
                ServiceCode="AmazonBedrock",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Machine Learning"},
                    {"Type": "TERM_MATCH", "Field": "modelId", "Value": f"anthropic.claude-{family}"},
                ],
                MaxResults=10,
            )

            # Parse pricing from response
            for product_json in response.get("PriceList", []):
                product = json.loads(product_json) if isinstance(product_json, str) else product_json
                terms = product.get("terms", {}).get("OnDemand", {})
                for term in terms.values():
                    for dimension in term.get("priceDimensions", {}).values():
                        price_per_unit = float(dimension.get("pricePerUnit", {}).get("USD", "0"))
                        description = dimension.get("description", "").lower()
                        if price_per_unit > 0:
                            if family not in prices:
                                prices[family] = {}
                            if "input" in description:
                                prices[family]["input"] = price_per_unit * 1_000_000
                            elif "output" in description:
                                prices[family]["output"] = price_per_unit * 1_000_000

        if prices:
            # Merge with defaults for any missing fields
            for family in DEFAULT_PRICES:
                if family not in prices:
                    prices[family] = DEFAULT_PRICES[family]
                else:
                    for key in DEFAULT_PRICES[family]:
                        if key not in prices[family]:
                            prices[family][key] = DEFAULT_PRICES[family][key]

            # Cache
            _pricing_cache["prices"] = prices
            _pricing_cache["fetched_at"] = now
            with open(CACHE_FILE, "w") as f:
                json.dump({"prices": prices, "fetched_at": now}, f)

            return prices

    except Exception as e:
        print(f"Pricing API error (using defaults): {e}")

    return DEFAULT_PRICES


def lambda_handler(event, context):
    """Main handler — query token usage, calculate cost, publish metrics."""
    cw = boto3.client("cloudwatch", region_name=REGION)
    prices = fetch_bedrock_prices()

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=1)

    # Query token usage by model and type for the last hour
    try:
        response = cw.get_metric_data(
            MetricDataQueries=[
                {
                    "Id": "tokens",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": NAMESPACE,
                            "MetricName": "claude_code.token.usage",
                        },
                        "Period": 3600,
                        "Stat": "Sum",
                    },
                    "ReturnData": True,
                }
            ],
            StartTime=start_time,
            EndTime=end_time,
        )
    except Exception as e:
        print(f"Error querying metrics: {e}")
        return {"statusCode": 500, "body": str(e)}

    # Also query with model dimension for per-model breakdown
    # Use list_metrics to discover active models
    try:
        metrics_response = cw.list_metrics(
            Namespace=NAMESPACE,
            MetricName="claude_code.token.usage",
            Dimensions=[{"Name": "model"}],
        )

        metric_data_queries = []
        model_map = {}

        for i, metric in enumerate(metrics_response.get("Metrics", [])):
            model_dim = next(
                (d["Value"] for d in metric.get("Dimensions", []) if d["Name"] == "model"),
                None
            )
            if model_dim:
                query_id = f"m{i}"
                model_map[query_id] = model_dim
                metric_data_queries.append({
                    "Id": query_id,
                    "MetricStat": {
                        "Metric": {
                            "Namespace": NAMESPACE,
                            "MetricName": "claude_code.token.usage",
                            "Dimensions": [{"Name": "model", "Value": model_dim}],
                        },
                        "Period": 3600,
                        "Stat": "Sum",
                    },
                    "ReturnData": True,
                })

        if metric_data_queries:
            model_response = cw.get_metric_data(
                MetricDataQueries=metric_data_queries[:500],  # API limit
                StartTime=start_time,
                EndTime=end_time,
            )

            # Calculate and publish cost metrics
            metric_data = []
            for result in model_response.get("MetricDataResults", []):
                query_id = result["Id"]
                model_id = model_map.get(query_id, "unknown")
                family = get_model_family(model_id)
                family_prices = prices.get(family, DEFAULT_PRICES.get("sonnet", {}))

                for timestamp, value in zip(result.get("Timestamps", []), result.get("Values", [])):
                    # Default to input pricing (most common); type dimension would refine this
                    cost_per_1m = family_prices.get("input", 3.0)
                    estimated_cost = (value / 1_000_000) * cost_per_1m

                    metric_data.append({
                        "MetricName": "claude_code.cost.estimated",
                        "Timestamp": timestamp,
                        "Value": estimated_cost,
                        "Unit": "None",
                        "Dimensions": [
                            {"Name": "model", "Value": model_id},
                            {"Name": "model_family", "Value": family},
                        ],
                    })

            # Publish in batches of 1000 (API limit)
            for i in range(0, len(metric_data), 1000):
                batch = metric_data[i:i + 1000]
                cw.put_metric_data(Namespace=NAMESPACE, MetricData=batch)

            print(f"Published {len(metric_data)} cost metrics for {len(model_map)} models")

    except Exception as e:
        print(f"Error processing per-model metrics: {e}")

    return {"statusCode": 200, "body": f"Cost estimation complete"}
