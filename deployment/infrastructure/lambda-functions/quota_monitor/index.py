# ABOUTME: Lambda function that monitors user token quotas and sends SNS alerts
# ABOUTME: Supports fine-grained quota policies (user, group, default) with token tracking

import json
import boto3
import os
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

# Initialize clients
dynamodb = boto3.resource("dynamodb")
sns_client = boto3.client("sns")

# Configuration from environment
QUOTA_TABLE = os.environ.get("QUOTA_TABLE", "UserQuotaMetrics")
POLICIES_TABLE = os.environ.get("POLICIES_TABLE")  # Optional - for fine-grained quotas
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")
ENABLE_FINEGRAINED_QUOTAS = os.environ.get("ENABLE_FINEGRAINED_QUOTAS", "false").lower() == "true"

# Default limits (used when no policy is defined)
MONTHLY_TOKEN_LIMIT = int(os.environ.get("MONTHLY_TOKEN_LIMIT", "300000000"))  # 300M default
WARNING_THRESHOLD_80 = int(os.environ.get("WARNING_THRESHOLD_80", "240000000"))  # 240M
WARNING_THRESHOLD_90 = int(os.environ.get("WARNING_THRESHOLD_90", "270000000"))  # 270M

# DynamoDB tables
quota_table = dynamodb.Table(QUOTA_TABLE)
policies_table = dynamodb.Table(POLICIES_TABLE) if POLICIES_TABLE else None


def lambda_handler(event, context):
    """
    Check user token usage against quotas (fine-grained or default) and send alerts.
    Supports monthly, daily, and cost-based limits.
    """
    print(f"Starting quota monitoring check at {datetime.now(timezone.utc).isoformat()}")
    print(f"Fine-grained quotas: {'enabled' if ENABLE_FINEGRAINED_QUOTAS else 'disabled'}")

    # Get current calendar month boundaries
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_name = now.strftime("%B %Y")
    current_date = now.strftime("%Y-%m-%d")
    days_in_month = (
        31
        if now.month in [1, 3, 5, 7, 8, 10, 12]
        else (30 if now.month != 2 else (29 if now.year % 4 == 0 else 28))
    )
    days_remaining = days_in_month - now.day

    print(f"Checking usage for {month_name} (day {now.day}/{days_in_month})")

    try:
        # Get user usage data for this month
        user_usage_data = get_monthly_usage(month_name)

        if not user_usage_data:
            print("No user metrics found for current month")
            return {"statusCode": 200, "body": json.dumps("No usage data found")}

        # Load policies if fine-grained quotas are enabled
        policies_cache = {}
        if ENABLE_FINEGRAINED_QUOTAS and policies_table:
            policies_cache = load_all_policies()
            print(f"Loaded {len(policies_cache)} policies")

        # Check alerts that have already been sent this month
        sent_alerts = get_sent_alerts(month_name)

        # Process each user
        alerts_to_send = []
        stats = {"total_users": 0, "over_80": 0, "over_90": 0, "exceeded": 0, "daily_exceeded": 0}

        for email, usage in user_usage_data.items():
            stats["total_users"] += 1

            # Resolve the effective quota policy for this user
            policy = resolve_user_quota(email, usage.get("groups", []), policies_cache)

            if policy is None:
                # No policy = unlimited (skip this user)
                continue

            total_tokens = float(usage.get("total_tokens", 0))
            daily_tokens = float(usage.get("daily_tokens", 0))

            # Check all limit types and generate alerts
            alerts = check_limits_and_generate_alerts(
                email=email,
                total_tokens=total_tokens,
                daily_tokens=daily_tokens,
                policy=policy,
                month_name=month_name,
                current_date=current_date,
                days_remaining=days_remaining,
                days_in_month=days_in_month,
                sent_alerts=sent_alerts,
            )

            # Update statistics
            monthly_pct = (total_tokens / policy["monthly_token_limit"]) * 100 if policy["monthly_token_limit"] > 0 else 0
            if monthly_pct > 100:
                stats["exceeded"] += 1
            elif monthly_pct > 90:
                stats["over_90"] += 1
            elif monthly_pct > 80:
                stats["over_80"] += 1

            if policy.get("daily_token_limit") and daily_tokens > policy["daily_token_limit"]:
                stats["daily_exceeded"] += 1

            # Add alerts to send list
            for alert in alerts:
                alert_key = f"{email}#{alert['alert_type']}#{alert['alert_level']}"
                if alert_key not in sent_alerts:
                    alerts_to_send.append(alert)
                    # Record alert to prevent duplicates
                    record_sent_alert(month_name, email, alert["alert_type"], alert["alert_level"], alert)

        # Send alerts via SNS
        if alerts_to_send:
            send_alerts(alerts_to_send)
            print(f"Sent {len(alerts_to_send)} quota alerts")
        else:
            print("No new alerts to send")

        # Log summary statistics
        print(f"Summary - Total: {stats['total_users']}, Over 80%: {stats['over_80']}, Over 90%: {stats['over_90']}, Exceeded: {stats['exceeded']}")
        if ENABLE_FINEGRAINED_QUOTAS:
            print(f"  Daily exceeded: {stats['daily_exceeded']}")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "users_checked": stats["total_users"],
                "alerts_sent": len(alerts_to_send),
                "users_over_80": stats["over_80"],
                "users_over_90": stats["over_90"],
                "users_exceeded": stats["exceeded"],
                "daily_exceeded": stats["daily_exceeded"],
            }),
        }

    except Exception as e:
        print(f"Error during quota monitoring: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps(f"Error: {str(e)}")}


def get_monthly_usage(month_name):
    """
    Query the UserQuotaMetrics table for all users in the current month.
    Returns dict of email -> usage data including token types and cost.
    """
    user_usage = {}

    # Extract YYYY-MM format from month_name
    now = datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")

    try:
        # Scan for all users in this month with enhanced fields
        response = quota_table.scan(
            FilterExpression=Attr("sk").eq(f"MONTH#{month_prefix}"),
            ProjectionExpression="email, total_tokens, daily_tokens, daily_date, input_tokens, output_tokens, cache_tokens, estimated_cost, #groups",
            ExpressionAttributeNames={"#groups": "groups"},
        )

        # Process results
        for item in response.get("Items", []):
            email = item.get("email")
            if email:
                user_usage[email] = {
                    "total_tokens": float(item.get("total_tokens", 0)),
                    "daily_tokens": float(item.get("daily_tokens", 0)),
                    "daily_date": item.get("daily_date"),
                    "input_tokens": float(item.get("input_tokens", 0)),
                    "output_tokens": float(item.get("output_tokens", 0)),
                    "cache_tokens": float(item.get("cache_tokens", 0)),
                    "estimated_cost": float(item.get("estimated_cost", 0)),
                    "groups": item.get("groups", []),
                }

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = quota_table.scan(
                FilterExpression=Attr("sk").eq(f"MONTH#{month_prefix}"),
                ProjectionExpression="email, total_tokens, daily_tokens, daily_date, input_tokens, output_tokens, cache_tokens, estimated_cost, #groups",
                ExpressionAttributeNames={"#groups": "groups"},
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )

            for item in response.get("Items", []):
                email = item.get("email")
                if email:
                    user_usage[email] = {
                        "total_tokens": float(item.get("total_tokens", 0)),
                        "daily_tokens": float(item.get("daily_tokens", 0)),
                        "daily_date": item.get("daily_date"),
                        "input_tokens": float(item.get("input_tokens", 0)),
                        "output_tokens": float(item.get("output_tokens", 0)),
                        "cache_tokens": float(item.get("cache_tokens", 0)),
                        "estimated_cost": float(item.get("estimated_cost", 0)),
                        "groups": item.get("groups", []),
                    }

        print(f"Found {len(user_usage)} users with usage in {month_prefix}")

    except Exception as e:
        print(f"Error querying quota table: {str(e)}")
        raise

    return user_usage


def load_all_policies():
    """
    Load all quota policies from the QuotaPolicies table.
    Returns dict keyed by policy type and identifier.
    """
    policies = {}

    if not policies_table:
        return policies

    try:
        response = policies_table.scan(
            FilterExpression=Attr("sk").eq("CURRENT"),
        )

        for item in response.get("Items", []):
            policy_type = item.get("policy_type")
            identifier = item.get("identifier")

            if policy_type and identifier:
                key = f"{policy_type}:{identifier}"
                policies[key] = {
                    "policy_type": policy_type,
                    "identifier": identifier,
                    "monthly_token_limit": int(item.get("monthly_token_limit", 0)),
                    "daily_token_limit": int(item.get("daily_token_limit", 0)) if item.get("daily_token_limit") else None,
                    "warning_threshold_80": int(item.get("warning_threshold_80", 0)),
                    "warning_threshold_90": int(item.get("warning_threshold_90", 0)),
                    "enforcement_mode": item.get("enforcement_mode", "alert"),
                    "enabled": item.get("enabled", True),
                }

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = policies_table.scan(
                FilterExpression=Attr("sk").eq("CURRENT"),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )

            for item in response.get("Items", []):
                policy_type = item.get("policy_type")
                identifier = item.get("identifier")

                if policy_type and identifier:
                    key = f"{policy_type}:{identifier}"
                    policies[key] = {
                        "policy_type": policy_type,
                        "identifier": identifier,
                        "monthly_token_limit": int(item.get("monthly_token_limit", 0)),
                        "daily_token_limit": int(item.get("daily_token_limit", 0)) if item.get("daily_token_limit") else None,
                        "warning_threshold_80": int(item.get("warning_threshold_80", 0)),
                        "warning_threshold_90": int(item.get("warning_threshold_90", 0)),
                        "enforcement_mode": item.get("enforcement_mode", "alert"),
                        "enabled": item.get("enabled", True),
                    }

    except Exception as e:
        print(f"Error loading policies: {str(e)}")

    return policies


def resolve_user_quota(email, groups, policies_cache):
    """
    Resolve the effective quota policy for a user.
    Precedence: user-specific > group (most restrictive) > default > env defaults

    Args:
        email: User's email address.
        groups: List of group names from JWT claims.
        policies_cache: Dict of all loaded policies.

    Returns:
        Policy dict or None if no policy applies (unlimited).
    """
    if not ENABLE_FINEGRAINED_QUOTAS:
        # Return default limits from environment
        return {
            "policy_type": "default",
            "identifier": "environment",
            "monthly_token_limit": MONTHLY_TOKEN_LIMIT,
            "daily_token_limit": None,
            "warning_threshold_80": WARNING_THRESHOLD_80,
            "warning_threshold_90": WARNING_THRESHOLD_90,
            "enforcement_mode": "alert",
            "enabled": True,
        }

    # 1. Check for user-specific policy
    user_key = f"user:{email}"
    if user_key in policies_cache:
        policy = policies_cache[user_key]
        if policy.get("enabled"):
            return policy

    # 2. Check for group policies (apply most restrictive)
    group_policies = []
    for group in groups or []:
        group_key = f"group:{group}"
        if group_key in policies_cache:
            policy = policies_cache[group_key]
            if policy.get("enabled"):
                group_policies.append(policy)

    if group_policies:
        # Most restrictive = lowest monthly_token_limit
        return min(group_policies, key=lambda p: p["monthly_token_limit"])

    # 3. Fall back to default policy
    default_key = "default:default"
    if default_key in policies_cache:
        policy = policies_cache[default_key]
        if policy.get("enabled"):
            return policy

    # 4. No policy defined = unlimited (return None)
    return None


def check_limits_and_generate_alerts(
    email, total_tokens, daily_tokens, policy,
    month_name, current_date, days_remaining, days_in_month, sent_alerts
):
    """
    Check all limit types and generate appropriate alerts.
    Returns list of alert dicts.
    """
    alerts = []
    policy_info = f"{policy['policy_type']}:{policy['identifier']}"
    enforcement_mode = policy.get('enforcement_mode', 'alert')

    # 1. Check monthly token limit
    monthly_limit = policy["monthly_token_limit"]
    monthly_pct = (total_tokens / monthly_limit) * 100 if monthly_limit > 0 else 0
    daily_average = total_tokens / max(1, int(current_date.split("-")[2]))
    projected_total = daily_average * days_in_month

    monthly_alert_level = None
    if total_tokens > monthly_limit:
        monthly_alert_level = "exceeded"
    elif total_tokens > policy["warning_threshold_90"]:
        monthly_alert_level = "critical"
    elif total_tokens > policy["warning_threshold_80"]:
        monthly_alert_level = "warning"

    if monthly_alert_level:
        alert_key = f"{email}#monthly#{monthly_alert_level}"
        if alert_key not in sent_alerts:
            alerts.append({
                "user": email,
                "alert_type": "monthly",
                "alert_level": monthly_alert_level,
                "current_usage": int(total_tokens),
                "limit": monthly_limit,
                "percentage": round(monthly_pct, 1),
                "month": month_name,
                "days_remaining": days_remaining,
                "daily_average": int(daily_average),
                "projected_total": int(projected_total),
                "policy_info": policy_info,
                "enforcement_mode": enforcement_mode,
            })

    # 2. Check daily token limit (if configured)
    daily_limit = policy.get("daily_token_limit")
    if daily_limit:
        daily_pct = (daily_tokens / daily_limit) * 100 if daily_limit > 0 else 0

        daily_alert_level = None
        if daily_tokens > daily_limit:
            daily_alert_level = "exceeded"
        elif daily_tokens > (daily_limit * 0.9):
            daily_alert_level = "critical"
        elif daily_tokens > (daily_limit * 0.8):
            daily_alert_level = "warning"

        if daily_alert_level:
            # Daily alerts use date in key so they can repeat each day
            alert_key = f"{email}#daily#{current_date}#{daily_alert_level}"
            if alert_key not in sent_alerts:
                alerts.append({
                    "user": email,
                    "alert_type": "daily",
                    "alert_level": daily_alert_level,
                    "current_usage": int(daily_tokens),
                    "limit": daily_limit,
                    "percentage": round(daily_pct, 1),
                    "date": current_date,
                    "policy_info": policy_info,
                    "enforcement_mode": enforcement_mode,
                })

    return alerts


def get_sent_alerts(month_name):
    """
    Get list of alerts already sent this month to avoid duplicates.
    Returns set of alert key strings.
    """
    sent_alerts = set()

    try:
        month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")

        response = quota_table.query(
            KeyConditionExpression=Key("pk").eq("ALERTS")
            & Key("sk").begins_with(f"{month_prefix}#ALERT#")
        )

        for item in response.get("Items", []):
            # Parse SK to get email, type, and level
            sk_parts = item["sk"].split("#")
            if len(sk_parts) >= 5:
                email = sk_parts[2]
                alert_type = sk_parts[3]
                alert_level = sk_parts[4]
                # For daily alerts, include date
                if alert_type == "daily" and len(sk_parts) >= 6:
                    date = sk_parts[5]
                    sent_alerts.add(f"{email}#{alert_type}#{date}#{alert_level}")
                else:
                    sent_alerts.add(f"{email}#{alert_type}#{alert_level}")

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = quota_table.query(
                KeyConditionExpression=Key("pk").eq("ALERTS")
                & Key("sk").begins_with(f"{month_prefix}#ALERT#"),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )

            for item in response.get("Items", []):
                sk_parts = item["sk"].split("#")
                if len(sk_parts) >= 5:
                    email = sk_parts[2]
                    alert_type = sk_parts[3]
                    alert_level = sk_parts[4]
                    if alert_type == "daily" and len(sk_parts) >= 6:
                        date = sk_parts[5]
                        sent_alerts.add(f"{email}#{alert_type}#{date}#{alert_level}")
                    else:
                        sent_alerts.add(f"{email}#{alert_type}#{alert_level}")

        if sent_alerts:
            print(f"Found {len(sent_alerts)} alerts already sent this month")

    except Exception as e:
        print(f"Error checking sent alerts: {str(e)}")

    return sent_alerts


def record_sent_alert(month_name, email, alert_type, alert_level, alert_data):
    """
    Record that an alert was sent to prevent duplicates.
    """
    try:
        month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")

        # Build SK based on alert type
        if alert_type == "daily":
            date = alert_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            sk = f"{month_prefix}#ALERT#{email}#{alert_type}#{alert_level}#{date}"
        else:
            sk = f"{month_prefix}#ALERT#{email}#{alert_type}#{alert_level}"

        quota_table.put_item(
            Item={
                "pk": "ALERTS",
                "sk": sk,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "month": month_name,
                "email": email,
                "alert_type": alert_type,
                "alert_level": alert_level,
                "usage_at_alert": Decimal(str(alert_data.get("current_usage", 0))),
                "limit_at_alert": Decimal(str(alert_data.get("limit", 0))),
                "policy_info": alert_data.get("policy_info", ""),
                "ttl": int((datetime.now(timezone.utc).timestamp())) + (60 * 86400),  # 60 day TTL
            }
        )
        print(f"Recorded {alert_type} {alert_level} alert for {email}")

    except Exception as e:
        print(f"Error recording sent alert: {str(e)}")


def send_alerts(alerts):
    """
    Send alerts via SNS with enhanced formatting for different alert types.
    """
    if not SNS_TOPIC_ARN:
        print("Warning: SNS_TOPIC_ARN not configured - skipping alert sending")
        return

    for alert in alerts:
        try:
            alert_type = alert.get("alert_type", "monthly")
            alert_level = alert["alert_level"]

            # Create subject based on alert type and level
            level_prefix = {
                "warning": "WARNING",
                "critical": "CRITICAL",
                "exceeded": "EXCEEDED",
            }.get(alert_level, "ALERT")

            type_label = {
                "monthly": "Monthly Token Quota",
                "daily": "Daily Token Quota",
            }.get(alert_type, "Quota")

            subject = f"Claude Code {level_prefix} - {type_label} - {alert['percentage']:.0f}%"

            # Format the message body based on alert type
            if alert_type == "monthly":
                message = format_monthly_alert(alert)
            elif alert_type == "daily":
                message = format_daily_alert(alert)
            else:
                message = format_monthly_alert(alert)

            # Send to SNS
            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=subject,
                Message=message,
                MessageAttributes={
                    "user": {"DataType": "String", "StringValue": alert["user"]},
                    "alert_type": {"DataType": "String", "StringValue": alert_type},
                    "alert_level": {"DataType": "String", "StringValue": alert_level},
                    "percentage": {"DataType": "Number", "StringValue": str(alert["percentage"])},
                },
            )

            print(f"Sent {alert_type} {alert_level} alert for {alert['user']} ({alert['percentage']:.1f}%)")

        except Exception as e:
            print(f"Error sending alert for {alert['user']}: {str(e)}")


def format_monthly_alert(alert):
    """Format monthly token quota alert message with prominent user email."""
    enforcement = alert.get('enforcement_mode', 'alert')
    user_email = alert['user']

    return f"""
=====================================
CLAUDE CODE QUOTA ALERT
=====================================

USER: {user_email}
ALERT: Monthly Token Quota - {alert['alert_level'].upper()}
MONTH: {alert.get('month', 'N/A')}

-------------------------------------
CURRENT USAGE
-------------------------------------
Monthly Tokens: {alert['current_usage']:,} / {alert['limit']:,} ({alert['percentage']:.1f}%)
Daily Average: {alert.get('daily_average', 0):,} tokens
Projected Monthly: {alert.get('projected_total', 0):,} tokens

Days Remaining: {alert.get('days_remaining', 'N/A')}

Policy: {alert.get('policy_info', 'default')}
Enforcement: {enforcement}

-------------------------------------
ACTION REQUIRED
-------------------------------------
{"ACCESS IS BLOCKED until quota resets or admin unblocks." if enforcement == "block" and alert['alert_level'] == 'exceeded' else "User may soon exceed quota limit."}

To temporarily unblock this user:
  ccwb quota unblock {user_email} --duration 24h

To increase their quota:
  ccwb quota set-user {user_email} --monthly-limit 500M

=====================================
This alert is sent once per threshold level per month.
"""


def format_daily_alert(alert):
    """Format daily token quota alert message with prominent user email."""
    enforcement = alert.get('enforcement_mode', 'alert')
    user_email = alert['user']

    return f"""
=====================================
CLAUDE CODE QUOTA ALERT
=====================================

USER: {user_email}
ALERT: Daily Token Quota - {alert['alert_level'].upper()}
DATE: {alert.get('date', 'N/A')}

-------------------------------------
CURRENT USAGE
-------------------------------------
Daily Tokens: {alert['current_usage']:,} / {alert['limit']:,} ({alert['percentage']:.1f}%)

Policy: {alert.get('policy_info', 'default')}
Enforcement: {enforcement}

-------------------------------------
ACTION REQUIRED
-------------------------------------
{"ACCESS IS BLOCKED until daily quota resets at UTC midnight or admin unblocks." if enforcement == "block" and alert['alert_level'] == 'exceeded' else "User may soon exceed daily quota limit."}

To temporarily unblock this user:
  ccwb quota unblock {user_email} --duration 24h

To increase their daily quota:
  ccwb quota set-user {user_email} --daily-limit 20M

=====================================
Daily quotas reset at UTC midnight.
"""
