"""AllCode Nexus - Multi-Tenant AWS Marketplace Metering Lambda.

Runs hourly via EventBridge. For each org in NexusOrganizations:
1. Assumes cross-account role to read their ClaudeCodeMetrics
2. Calculates cost (tokens × price × markup)
3. Reports to AWS Marketplace via BatchMeterUsage
"""

import json
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

ORGS_TABLE = os.environ.get("ORGS_TABLE", "NexusOrganizations")
CHECKPOINTS_TABLE = os.environ.get("CHECKPOINTS_TABLE", "MeteringCheckpoints")
PRODUCT_CODE = os.environ.get("MARKETPLACE_PRODUCT_CODE", "")
LOCAL_METRICS_TABLE = os.environ.get("METRICS_TABLE", "ClaudeCodeMetrics")

MODEL_PRICING = {
    "claude-sonnet": 8.00,
    "claude-haiku": 2.00,
    "claude-opus": 30.00,
    "default": 8.00,
}
MARKUP = 1.30

dynamodb = boto3.resource("dynamodb")
checkpoints_table = dynamodb.Table(CHECKPOINTS_TABLE)
orgs_table = dynamodb.Table(ORGS_TABLE)
marketplace = boto3.client("meteringmarketplace")
sts = boto3.client("sts")


def get_checkpoint(org_id: str) -> str:
    try:
        result = checkpoints_table.get_item(Key={"pk": f"CHECKPOINT#{org_id}", "sk": "LATEST"})
        return result.get("Item", {}).get("timestamp", "1970-01-01T00:00:00Z")
    except Exception:
        return "1970-01-01T00:00:00Z"


def save_checkpoint(org_id: str, timestamp: str, tokens: int, cost_cents: int):
    checkpoints_table.put_item(Item={
        "pk": f"CHECKPOINT#{org_id}",
        "sk": "LATEST",
        "timestamp": timestamp,
        "metered_at": datetime.now(timezone.utc).isoformat(),
        "tokens_reported": tokens,
        "cost_cents": cost_cents,
    })


def get_org_metrics_table(org):
    """Get a DynamoDB table resource for an org (cross-account if needed)."""
    role_arn = org.get("role_arn", "")
    region = org.get("region", "us-east-1")

    if not role_arn:
        # Local org (allcode)
        return dynamodb.Table(LOCAL_METRICS_TABLE)

    # Cross-account: assume the connector role
    creds = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName="nexus-metering",
    )["Credentials"]

    remote_session = boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )
    remote_ddb = remote_session.resource("dynamodb")
    return remote_ddb.Table("ClaudeCodeMetrics")


def query_usage_since(table, last_checkpoint: str) -> dict:
    """Query token usage since last checkpoint."""
    total_tokens = 0
    latest_timestamp = last_checkpoint

    try:
        result = table.query(
            KeyConditionExpression=Key("pk").eq("METRICS") & Key("sk").gt(last_checkpoint),
            Limit=1000,
            ScanIndexForward=True,
        )
        for item in result.get("Items", []):
            sk = item.get("sk", "")
            if "#WINDOW#SUMMARY" in sk:
                total_tokens += int(item.get("total_tokens", 0))
                ts = item.get("timestamp", "")
                if ts > latest_timestamp:
                    latest_timestamp = ts
    except Exception as e:
        print(f"Error querying metrics: {e}")

    return {"total_tokens": total_tokens, "latest_timestamp": latest_timestamp}


def meter_org(org):
    """Meter usage for a single org."""
    org_id = org.get("pk", "").replace("ORG#", "")
    customer_id = org.get("marketplace_customer_id", "")

    if not customer_id:
        print(f"  {org_id}: no marketplace_customer_id, skipping")
        return

    last_checkpoint = get_checkpoint(org_id)
    metrics_table = get_org_metrics_table(org)
    usage = query_usage_since(metrics_table, last_checkpoint)
    total_tokens = usage["total_tokens"]
    latest_timestamp = usage["latest_timestamp"]

    if total_tokens == 0:
        print(f"  {org_id}: no new usage")
        return

    # Calculate cost in cents
    price_per_million = MODEL_PRICING["default"]
    cost_cents = int((total_tokens / 1_000_000) * price_per_million * MARKUP * 100)

    if cost_cents == 0:
        print(f"  {org_id}: {total_tokens} tokens below minimum")
        save_checkpoint(org_id, latest_timestamp, total_tokens, 0)
        return

    # Report to Marketplace
    now = datetime.now(timezone.utc)
    try:
        response = marketplace.batch_meter_usage(
            UsageRecords=[{
                "CustomerIdentifier": customer_id,
                "Dimension": "bedrock_usage_cents",
                "Quantity": cost_cents,
                "Timestamp": int(now.timestamp()),
            }],
            ProductCode=PRODUCT_CODE,
        )
        results = response.get("Results", [])
        print(f"  {org_id}: metered {cost_cents} cents ({total_tokens} tokens) - {results}")
        save_checkpoint(org_id, latest_timestamp, total_tokens, cost_cents)
    except Exception as e:
        print(f"  {org_id}: FAILED to meter - {e}")


def lambda_handler(event, context):
    """Main handler - iterates all orgs and meters each."""
    if not PRODUCT_CODE:
        print("No MARKETPLACE_PRODUCT_CODE configured. Skipping.")
        return {"statusCode": 200, "body": "not configured"}

    # Get all active orgs
    try:
        result = orgs_table.scan(
            FilterExpression="attribute_exists(marketplace_customer_id)"
        )
        orgs = result.get("Items", [])
    except Exception as e:
        print(f"Failed to scan orgs: {e}")
        return {"statusCode": 500, "body": str(e)}

    # Also check for legacy single-customer config
    legacy_customer = os.environ.get("MARKETPLACE_CUSTOMER_ID", "")
    if legacy_customer and not orgs:
        orgs = [{"pk": "ORG#allcode", "marketplace_customer_id": legacy_customer}]

    print(f"Metering {len(orgs)} org(s)")
    for org in orgs:
        meter_org(org)

    return {"statusCode": 200, "body": f"metered {len(orgs)} orgs"}
