# ABOUTME: Lambda that detects users invoking Bedrock without a running OTEL sidecar
# ABOUTME: Joins CloudTrail Bedrock activity (tamper-proof) against OTEL-reported usage in DynamoDB

import json
import os
from datetime import datetime, timedelta, timezone

import boto3

# Clients
cloudtrail = boto3.client("cloudtrail")
cloudwatch = boto3.client("cloudwatch")
sns_client = boto3.client("sns")
dynamodb = boto3.resource("dynamodb")

# Configuration from environment
QUOTA_TABLE = os.environ.get("QUOTA_TABLE", "UserQuotaMetrics")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")
METRICS_REGION = os.environ.get("METRICS_REGION", os.environ.get("AWS_REGION", "us-east-1"))
LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "15"))
CLOUDWATCH_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "ClaudeCode/SidecarHealth")

quota_table = dynamodb.Table(QUOTA_TABLE)

# Bedrock runtime events logged as CloudTrail management events
BEDROCK_INVOKE_EVENTS = {"InvokeModel", "InvokeModelWithResponseStream", "Converse", "ConverseStream"}


def _extract_email_from_arn(arn):
    """Extract the role session name (= user email) from an assumed-role ARN.

    Session name is set to the user's email by the credential provider, e.g.:
      arn:aws:sts::123456789012:assumed-role/ClaudeCodeRole/alice@example.com
    Returns the email portion, or None if the ARN is not an assumed-role ARN.
    """
    if not arn or ":assumed-role/" not in arn:
        return None
    session_name = arn.rsplit("/", 1)[-1]
    # Emails are preserved by the credential provider's sanitizer ([\w+=,.@-]).
    # Require an @ to avoid counting non-user sessions (e.g. "claude-code").
    if "@" not in session_name:
        return None
    return session_name.lower()


def get_bedrock_active_users(start_time, end_time):
    """Return the set of user emails that invoked Bedrock in the window via CloudTrail.

    Uses CloudTrail LookupEvents (management events, captured by default - no trail
    or data-event charges required).
    """
    active_users = set()
    paginator = cloudtrail.get_paginator("lookup_events")

    for event_name in BEDROCK_INVOKE_EVENTS:
        try:
            pages = paginator.paginate(
                LookupAttributes=[{"AttributeKey": "EventName", "AttributeValue": event_name}],
                StartTime=start_time,
                EndTime=end_time,
                PaginationConfig={"MaxItems": 5000, "PageSize": 50},
            )
            for page in pages:
                for event in page.get("Events", []):
                    try:
                        record = json.loads(event["CloudTrailEvent"])
                    except (KeyError, json.JSONDecodeError):
                        continue
                    arn = record.get("userIdentity", {}).get("arn", "")
                    email = _extract_email_from_arn(arn)
                    if email:
                        active_users.add(email)
        except Exception as e:
            print(f"Error looking up {event_name} events: {e}")

    print(f"CloudTrail: {len(active_users)} users invoked Bedrock in last {LOOKBACK_MINUTES} min")
    return active_users


def is_reporting_telemetry(email, window_start):
    """Return True if the user reported OTEL telemetry within the window.

    Performs a single point read (GetItem) on the user's current-month record.
    The quota_monitor Lambda stamps `last_updated` whenever it processes OTEL
    usage for a user, so a fresh timestamp means the sidecar is reporting.

    Reads scale with the number of Bedrock-active users (the working set), not
    the total number of users in the table - so no full-table Scan is needed.

    A missing record (or one with no/old `last_updated`) means no telemetry was
    reported in the window, i.e. the sidecar is stopped.
    """
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        response = quota_table.get_item(
            Key={"pk": f"USER#{email}", "sk": f"MONTH#{current_month}"},
            ProjectionExpression="last_updated",
        )
    except Exception as e:
        # On read error, do not assert a bypass (avoid false positives).
        print(f"Error reading metrics for {email}: {e}")
        return True

    item = response.get("Item")
    if not item or not item.get("last_updated"):
        return False

    try:
        ts = datetime.fromisoformat(str(item["last_updated"]).replace("Z", "+00:00"))
    except ValueError:
        return False

    return ts >= window_start


def publish_metrics(stopped_users, active_users):
    """Publish per-user and aggregate sidecar health metrics to CloudWatch."""
    metric_data = [
        {
            "MetricName": "SidecarStoppedUserCount",
            "Value": len(stopped_users),
            "Unit": "Count",
            "Timestamp": datetime.now(timezone.utc),
        }
    ]
    for email in active_users:
        metric_data.append(
            {
                "MetricName": "SidecarStopped",
                "Dimensions": [{"Name": "user.email", "Value": email}],
                "Value": 1.0 if email in stopped_users else 0.0,
                "Unit": "Count",
                "Timestamp": datetime.now(timezone.utc),
            }
        )

    # CloudWatch PutMetricData accepts max 1000 metrics per call
    for i in range(0, len(metric_data), 1000):
        batch = metric_data[i : i + 1000]
        try:
            cloudwatch.put_metric_data(Namespace=CLOUDWATCH_NAMESPACE, MetricData=batch)
        except Exception as e:
            print(f"Error publishing metrics batch: {e}")


def send_alert(stopped_users):
    """Send an SNS alert listing users invoking Bedrock without a running sidecar."""
    if not SNS_TOPIC_ARN or not stopped_users:
        return

    user_list = "\n".join(f"  - {email}" for email in sorted(stopped_users))
    message = (
        "Claude Code Sidecar Health Alert\n\n"
        f"The following {len(stopped_users)} user(s) invoked Amazon Bedrock in the last "
        f"{LOOKBACK_MINUTES} minutes but reported NO telemetry via the OTEL sidecar.\n\n"
        "This means their token usage is NOT being counted toward quota limits. "
        "The sidecar collector may be stopped on their machine.\n\n"
        f"{user_list}\n\n"
        "Detection source: CloudTrail Bedrock management events (tamper-proof).\n"
        "Action: Verify the sidecar is running on these users' machines.\n"
    )
    try:
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Claude Code ALERT - {len(stopped_users)} user(s) with stopped sidecar",
            Message=message,
        )
        print(f"Sent sidecar alert for {len(stopped_users)} users")
    except Exception as e:
        print(f"Error sending SNS alert: {e}")


def lambda_handler(event, context):
    """Detect users invoking Bedrock without a running OTEL sidecar."""
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=LOOKBACK_MINUTES)
    print(f"Bypass detection: window {start_time.isoformat()} -> {now.isoformat()}")

    # 1. Tamper-proof: who actually called Bedrock (from CloudTrail)
    bedrock_users = get_bedrock_active_users(start_time, now)

    # 2. For each active user, check telemetry freshness via a point read.
    #    Active in Bedrock but not reporting telemetry => sidecar stopped/bypassed.
    stopped_users = {
        email for email in bedrock_users if not is_reporting_telemetry(email, start_time)
    }

    if stopped_users:
        print(f"DETECTED {len(stopped_users)} users with stopped sidecar: {sorted(stopped_users)}")
    else:
        print("No sidecar bypass detected")

    publish_metrics(stopped_users, bedrock_users)
    send_alert(stopped_users)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "bedrock_active_users": len(bedrock_users),
                "sidecar_stopped_users": sorted(stopped_users),
            }
        ),
    }
