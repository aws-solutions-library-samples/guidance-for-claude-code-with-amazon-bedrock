"""AllCode Nexus Governance Agent for AWS Transform Composability.

Enforces budgets, attributes costs, and detects anomalies during Transform runs.
Registered with Transform Composability and called at job lifecycle points.
"""

import json
import os
from datetime import datetime, timezone

import boto3
from flask import Flask, request, jsonify

app = Flask(__name__)

NEXUS_API_URL = os.environ.get("NEXUS_API_URL", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
policies_table = dynamodb.Table(os.environ.get("POLICIES_TABLE", "QuotaPolicies"))
metrics_table = dynamodb.Table(os.environ.get("METRICS_TABLE", "ClaudeCodeMetrics"))


@app.route("/v1/budget/check", methods=["POST"])
def budget_check():
    """Called before job starts. Check if team has budget remaining."""
    data = request.json
    team_id = data.get("team_id", "")
    estimated_tokens = data.get("estimated_tokens", 0)

    # Look up team's transform budget policy
    try:
        result = policies_table.get_item(Key={"pk": f"POLICY#transform", "sk": f"team#{team_id}"})
        policy = result.get("Item", {})
    except Exception:
        policy = {}

    max_tokens = int(policy.get("max_tokens_per_job", 10_000_000))
    action = policy.get("on_limit_exceeded", "fail_open")

    if estimated_tokens > max_tokens and action == "fail_closed":
        return jsonify({"allowed": False, "limit": max_tokens, "message": f"Estimated {estimated_tokens} tokens exceeds budget of {max_tokens}"})

    return jsonify({"allowed": True, "limit": max_tokens, "message": "Budget check passed"})


@app.route("/v1/cost/attribute", methods=["POST"])
def cost_attribute():
    """Called on job completion. Tag costs to team/project."""
    data = request.json
    team_id = data.get("team_id", "")
    job_id = data.get("job_id", "")
    actual_tokens = data.get("actual_tokens", 0)
    cost_usd = data.get("cost_usd", 0)

    tags = {
        "team_id": team_id,
        "job_id": job_id,
        "workload_type": "transform",
        "attributed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Write to metrics table
    try:
        metrics_table.put_item(Item={
            "pk": f"TRANSFORM#attribution",
            "sk": f"{job_id}#{datetime.now(timezone.utc).isoformat()}",
            "team_id": team_id,
            "tokens": actual_tokens,
            "cost_usd": str(cost_usd),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    return jsonify({"attributed": True, "tags": tags})


@app.route("/v1/anomaly/detect", methods=["POST"])
def anomaly_detect():
    """Called every 60s during job. Compare consumption against baseline."""
    data = request.json
    tokens_so_far = data.get("tokens_so_far", 0)
    expected = data.get("expected", 0)

    if expected > 0 and tokens_so_far > expected * 2:
        return jsonify({"anomaly": True, "severity": "high", "action": "alert"})
    elif expected > 0 and tokens_so_far > expected * 1.5:
        return jsonify({"anomaly": True, "severity": "medium", "action": "alert"})

    return jsonify({"anomaly": False, "severity": "none", "action": "continue"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
