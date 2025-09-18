# ABOUTME: Lambda function that monitors user token quotas and sends SNS alerts
# ABOUTME: Runs every 15 minutes to check monthly usage against thresholds

import json
import boto3
import os
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr
from collections import defaultdict

# Initialize clients
dynamodb = boto3.resource("dynamodb")
sns_client = boto3.client("sns")

# Configuration from environment
QUOTA_TABLE = os.environ.get("QUOTA_TABLE", "UserQuotaMetrics")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")
MONTHLY_TOKEN_LIMIT = int(
    os.environ.get("MONTHLY_TOKEN_LIMIT", "300000000")
)  # 300M default
WARNING_THRESHOLD_80 = int(os.environ.get("WARNING_THRESHOLD_80", "240000000"))  # 240M
WARNING_THRESHOLD_90 = int(os.environ.get("WARNING_THRESHOLD_90", "270000000"))  # 270M

# DynamoDB table
quota_table = dynamodb.Table(QUOTA_TABLE)


def lambda_handler(event, context):
    """
    Check user token usage against monthly quotas and send alerts.
    """
    print(
        f"Starting quota monitoring check at {datetime.now(timezone.utc).isoformat()}"
    )
    print(
        f"Limits - Monthly: {MONTHLY_TOKEN_LIMIT:,}, Warning 80%: {WARNING_THRESHOLD_80:,}, Warning 90%: {WARNING_THRESHOLD_90:,}"
    )

    # Get current calendar month boundaries
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_name = now.strftime("%B %Y")
    days_in_month = (
        31
        if now.month in [1, 3, 5, 7, 8, 10, 12]
        else (30 if now.month != 2 else (29 if now.year % 4 == 0 else 28))
    )
    days_remaining = days_in_month - now.day

    print(f"Checking usage for {month_name} (day {now.day}/{days_in_month})")

    try:
        # Query all user quotas for this month
        user_totals = get_monthly_quotas(month_name)

        if not user_totals:
            print("No user metrics found for current month")
            return {"statusCode": 200, "body": json.dumps("No usage data found")}

        # Check alerts that have already been sent this month
        sent_alerts = get_sent_alerts(month_name)

        # Process each user
        alerts_to_send = []
        for email, total_tokens in user_totals.items():
            # Calculate usage percentage
            percentage = (total_tokens / MONTHLY_TOKEN_LIMIT) * 100

            # Determine alert level
            alert_level = None
            if total_tokens > MONTHLY_TOKEN_LIMIT:
                alert_level = "exceeded"
            elif total_tokens > WARNING_THRESHOLD_90:
                alert_level = "critical"
            elif total_tokens > WARNING_THRESHOLD_80:
                alert_level = "warning"

            # Check if we should send an alert
            if alert_level:
                alert_key = f"{email}#{alert_level}"
                if alert_key not in sent_alerts:
                    # Prepare alert data
                    daily_average = total_tokens / now.day
                    projected_total = daily_average * days_in_month
                    projected_overage = max(0, projected_total - MONTHLY_TOKEN_LIMIT)

                    alert_data = {
                        "user": email,
                        "current_usage": int(total_tokens),
                        "monthly_limit": MONTHLY_TOKEN_LIMIT,
                        "percentage": round(percentage, 1),
                        "month": month_name,
                        "days_remaining": days_remaining,
                        "daily_average": int(daily_average),
                        "projected_overage": int(projected_overage),
                        "alert_level": alert_level,
                    }

                    alerts_to_send.append(alert_data)

                    # Record that we sent this alert
                    record_sent_alert(month_name, email, alert_level, total_tokens)
                else:
                    print(
                        f"Skipping {alert_level} alert for {email} - already sent this month"
                    )

        # Send alerts via SNS
        if alerts_to_send:
            send_alerts(alerts_to_send)
            print(f"Sent {len(alerts_to_send)} quota alerts")
        else:
            print("No new alerts to send")

        # Log summary statistics
        total_users = len(user_totals)
        users_over_80 = sum(
            1 for tokens in user_totals.values() if tokens > WARNING_THRESHOLD_80
        )
        users_over_90 = sum(
            1 for tokens in user_totals.values() if tokens > WARNING_THRESHOLD_90
        )
        users_exceeded = sum(
            1 for tokens in user_totals.values() if tokens > MONTHLY_TOKEN_LIMIT
        )

        print(
            f"Summary - Total users: {total_users}, Over 80%: {users_over_80}, Over 90%: {users_over_90}, Exceeded: {users_exceeded}"
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "users_checked": total_users,
                    "alerts_sent": len(alerts_to_send),
                    "users_over_80": users_over_80,
                    "users_over_90": users_over_90,
                    "users_exceeded": users_exceeded,
                }
            ),
        }

    except Exception as e:
        print(f"Error during quota monitoring: {str(e)}")
        return {"statusCode": 500, "body": json.dumps(f"Error: {str(e)}")}


def get_monthly_quotas(month_name):
    """
    Query the UserQuotaMetrics table for all users in the current month.
    Returns dict of email -> total_tokens.
    """
    user_totals = {}

    # Extract YYYY-MM format from month_name (e.g., "August 2025" -> "2025-08")
    now = datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")

    try:
        # Scan the quota table for all users in this month
        response = quota_table.scan(
            FilterExpression=Attr("sk").eq(f"MONTH#{month_prefix}"),
            ProjectionExpression="email, total_tokens",
        )

        # Process results
        for item in response.get("Items", []):
            email = item.get("email")
            total_tokens = float(item.get("total_tokens", 0))
            if email:
                user_totals[email] = total_tokens

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = quota_table.scan(
                FilterExpression=Attr("sk").eq(f"MONTH#{month_prefix}"),
                ProjectionExpression="email, total_tokens",
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )

            for item in response.get("Items", []):
                email = item.get("email")
                total_tokens = float(item.get("total_tokens", 0))
                if email:
                    user_totals[email] = total_tokens

        print(f"Found {len(user_totals)} users with usage in {month_prefix}")

        # Log top 5 users for debugging
        if user_totals:
            top_users = sorted(user_totals.items(), key=lambda x: x[1], reverse=True)[
                :5
            ]
            for email, tokens in top_users:
                print(
                    f"  {email}: {tokens:,.0f} tokens ({(tokens/MONTHLY_TOKEN_LIMIT)*100:.1f}%)"
                )

    except Exception as e:
        print(f"Error querying quota table: {str(e)}")
        raise

    return user_totals


def get_sent_alerts(month_name):
    """
    Get list of alerts already sent this month to avoid duplicates.
    Returns set of "email#alert_level" strings.
    """
    sent_alerts = set()

    try:
        # Query for ALERT entries for this month
        # SK format: YYYY-MM#ALERT#email#level
        month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")

        response = quota_table.query(
            KeyConditionExpression=Key("pk").eq("ALERTS")
            & Key("sk").begins_with(f"{month_prefix}#ALERT#")
        )

        for item in response.get("Items", []):
            # Parse SK to get email and level
            sk_parts = item["sk"].split("#")
            if len(sk_parts) >= 4:
                email = sk_parts[2]
                alert_level = sk_parts[3]
                sent_alerts.add(f"{email}#{alert_level}")

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = quota_table.query(
                KeyConditionExpression=Key("pk").eq("ALERTS")
                & Key("sk").begins_with(f"{month_prefix}#ALERT#"),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )

            for item in response.get("Items", []):
                sk_parts = item["sk"].split("#")
                if len(sk_parts) >= 4:
                    email = sk_parts[2]
                    alert_level = sk_parts[3]
                    sent_alerts.add(f"{email}#{alert_level}")

        if sent_alerts:
            print(f"Found {len(sent_alerts)} alerts already sent this month")

    except Exception as e:
        print(f"Error checking sent alerts: {str(e)}")
        # Continue anyway - better to send duplicate than miss an alert

    return sent_alerts


def record_sent_alert(month_name, email, alert_level, usage_at_alert):
    """
    Record that an alert was sent to prevent duplicates.
    """
    try:
        month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")

        quota_table.put_item(
            Item={
                "pk": "ALERTS",
                "sk": f"{month_prefix}#ALERT#{email}#{alert_level}",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "month": month_name,
                "email": email,
                "alert_level": alert_level,
                "usage_at_alert": Decimal(str(usage_at_alert)),
                "ttl": int((datetime.now(timezone.utc).timestamp()))
                + (60 * 86400),  # 60 day TTL
            }
        )
        print(f"Recorded {alert_level} alert for {email}")
    except Exception as e:
        print(f"Error recording sent alert: {str(e)}")
        # Continue anyway - duplicate alerts are better than missing alerts


def send_alerts(alerts):
    """
    Send alerts via SNS.
    """
    if not SNS_TOPIC_ARN:
        print("Warning: SNS_TOPIC_ARN not configured - skipping alert sending")
        return

    for alert in alerts:
        try:
            # Create readable subject based on alert level
            subject_map = {
                "warning": f"Claude Code Usage Alert - {alert['percentage']:.0f}% of Monthly Quota",
                "critical": f"Claude Code CRITICAL - {alert['percentage']:.0f}% of Monthly Quota",
                "exceeded": f"Claude Code EXCEEDED - {alert['percentage']:.0f}% of Monthly Quota",
            }
            subject = subject_map.get(alert["alert_level"], "Claude Code Usage Alert")

            # Format the message body
            message = f"""
Claude Code Usage Alert

User: {alert['user']}
Alert Level: {alert['alert_level'].upper()}
Month: {alert['month']}

Current Usage: {alert['current_usage']:,} tokens
Monthly Limit: {alert['monthly_limit']:,} tokens
Percentage Used: {alert['percentage']:.1f}%

Days Remaining in Month: {alert['days_remaining']}
Daily Average: {alert['daily_average']:,} tokens
Projected Monthly Total: {alert['current_usage'] + (alert['daily_average'] * alert['days_remaining']):,.0f} tokens
"""
            # Send to SNS
            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=subject,
                Message=message,
                MessageAttributes={
                    "user": {"DataType": "String", "StringValue": alert["user"]},
                    "alert_level": {
                        "DataType": "String",
                        "StringValue": alert["alert_level"],
                    },
                    "percentage": {
                        "DataType": "Number",
                        "StringValue": str(alert["percentage"]),
                    },
                    "month": {"DataType": "String", "StringValue": alert["month"]},
                },
            )

            print(
                f"Sent {alert['alert_level']} alert for {alert['user']} ({alert['percentage']:.1f}%)"
            )

        except Exception as e:
            print(f"Error sending alert for {alert['user']}: {str(e)}")
            # Continue with other alerts
